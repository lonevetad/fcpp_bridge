// Copyright © 2021 Giorgio Audrito. All Rights Reserved.

#ifndef REQUESTER_AMOUNT_
#define REQUESTER_AMOUNT_ 4
#endif

/**
 * @file exercises.cpp
 * @brief Quick-start aggregate computing exercises.
 */

// [INTRODUCTION]
//! Importing the FCPP library.
#include "lib/fcpp.hpp"
#include "run/shared.hpp"
#include "run/utils.hpp"
#include "run/storage_init.hpp"

using s_db_key = fcpp::device_t; // the "key" part of the key-value mapping implementing a "scattered database"
using s_db_data = fcpp::vec<2>;  // the "value" part of the key-value mapping implementing a "scattered database"


//! @brief Struct representing a data to be retrieved from a scattered database.
//template<>
class scattered_db_query/*<false>*/ {
  public:
    //! @brief the database KEY
    s_db_key key;
    //! @brief Receiver UID, the device/node who started this query
    fcpp::device_t requester;
    //! @brief Creation timestamp, but in "ticks".
    uint created_at_tick;
    //! @brief Creation timestamp.
    fcpp::times_t time;
    //! @brief counter, tracking how many times the device/node has asked for _some_ data
    // uint;

    //! @brief Empty constructor.
    scattered_db_query() = default;

    //! @brief Member constructor.
    scattered_db_query(
        s_db_key key,
        fcpp::device_t requester,
        uint created_at_tick,
        fcpp::times_t time
    ) : key(key), requester(requester), created_at_tick(created_at_tick), time(time) {}

    //! @brief Equality operator.
    bool operator==(scattered_db_query const& m) const {
        return key == m.key
            and requester == m.requester
            and(
                // ...  allow_multiple_queries is false
                // or
                // beware of "infinite" stream of messages
                created_at_tick == created_at_tick
                and time == m.time
            )
            ;
    }

    //! @brief Hash computation.
    size_t hash() const {
        constexpr size_t fields_count = 2;
        constexpr size_t offs = sizeof(size_t)*CHAR_BIT/fields_count;
        size_t partial = //
            ((size_t(requester) << offs))
            | (size_t(key))
            ;
        // removed to avoind "infinite" stream of messages
        return partial;
    }

    //! @brief Serialises the content from/to a given input/output stream.
    template <typename S>
    S& serialize(S& s) {
        return s & key & requester & created_at_tick & time;
    }

    //! @brief Serialises the content from/to a given input/output stream (const overload).
    template <typename S>
    S& serialize(S& s) const {
        return s << key << requester << created_at_tick << time;
    }

    //! @brief Returns a compact human-readable string representation.
    std::string to_string() const {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "%.3g", (double)time);
        return "db_qry{key=" + std::to_string(key)
            + " r=" + std::to_string(requester)
            + " ct=" + std::to_string(created_at_tick)
            + " ts=" + buf
            + "}";
    }
};


//! @brief Struct representing a data to be retrieved from a scattered database.
struct scattered_db_response {
    //! @brief the database KEY
    s_db_key key;
    //! @brief THE ACTUAL DATA
    s_db_data data;
    //! @brief Receiver UID, the device/node who started this query
    fcpp::device_t requester;
    //! @brief Replier UID, the device/node holding this query's response data
    fcpp::device_t holder;
    //! @brief Response's creation timestamp, but in "ticks".
    uint created_at_tick;
    //! @brief Response's creation timestamp.
    fcpp::times_t time;
    //! @brief counter, tracking how many times the device/node has asked for _some_ data
    // uint;

    //! @brief Empty constructor.
    scattered_db_response() = default;

    //! @brief Member constructor.
    scattered_db_response(
        s_db_key key,
        s_db_data data,
        fcpp::device_t requester,
        fcpp::device_t holder,
        uint created_at_tick,
        fcpp::times_t time
    ) : key(key), data(data), requester(requester), holder(holder), created_at_tick(created_at_tick), time(time) {}

    //! @brief Equality operator.
    bool operator==(scattered_db_response const& m) const {
        return key == m.key
            and data == m.data
            and requester == m.requester
            and holder == m.holder
            // removed to avoind "infinite" stream of messages
            // and created_at_tick == created_at_tick
            // and time == m.time
            ;
    }

    static size_t hash(s_db_data data_to_hash){
        constexpr size_t fields_count = 2;
        constexpr size_t offs = sizeof(size_t)*CHAR_BIT/fields_count;
        return (size_t(data_to_hash[1]) << offs) | size_t(data_to_hash[0]);
    }

    //! @brief Hash computation.
    size_t hash() const {
        constexpr size_t fields_count = 4;
        constexpr size_t offs = sizeof(size_t)*CHAR_BIT/fields_count;
        return  //((size_t(time) << (5*offs))
            // (size_t(created_at_tick) << (offs << 2))
            // removed to avoind "infinite" stream of messages
            ((size_t(holder) << (3*offs)))
            | ((size_t(requester) << (offs << 1)))
            | (hash(data) << offs)
            | (size_t(key));
    }

    //! @brief Serialises the content from/to a given input/output stream.
    template <typename S>
    S& serialize(S& s) {
        return s & key & data & requester & holder & created_at_tick & time;
    }

    //! @brief Serialises the content from/to a given input/output stream (const overload).
    template <typename S>
    S& serialize(S& s) const {
        return s << key << data << requester << holder << created_at_tick << time;
    }

    //! @brief Returns a compact human-readable string representation.
    std::string to_string() const {
        char buf[32];
        auto f3 = [&](double v) -> std::string {
            std::snprintf(buf, sizeof(buf), "%.3g", v);
            return buf;
        };
        return "db_res{key=" + std::to_string(key)
            + " d=(" + f3(data[0]) + "," + f3(data[1]) + ")"
            + " r=" + std::to_string(requester)
            + " h=" + std::to_string(holder)
            + " ct=" + std::to_string(created_at_tick)
            + " ts=" + f3(time)
            + "}";
    }
};


namespace std {
    //! @brief Hasher object for the scattered_db_query struct.
    template <>
    struct hash<scattered_db_query> {
        //! @brief Produces an hash for a scattered_db_query, combining its instance variables into a size_t.
        size_t operator()(scattered_db_query const& m) const {
            return m.hash();
        }
    };

    //! @brief Hasher object for the scattered_db_response struct.
    template <>
    struct hash<scattered_db_response> {
        //! @brief Produces an hash for a scattered_db_response, combining its instance variables into a size_t.
        size_t operator()(scattered_db_response const& m) const {
            return m.hash();
        }
    };
}




/**
 * @brief Namespace containing all the objects in the FCPP library.
 */
namespace fcpp {

//! @brief Namespace containing tnode_data_requestedhe libraries of coordination routines.
namespace coordination {



//! @brief Namespace for component options.
namespace option { // CONSTANTS
    //! @brief Number of people in the area.
    constexpr int node_num = 100;

    //! @brief Dimensionality of the space.
    constexpr size_t dim = 2;

    //! @brief Width of the network area (the GUI, actually).
    constexpr int network_width = 700;
    //! @brief Height of the network area (the GUI, actually).
    constexpr int network_height = 500;

    constexpr device_t another_ID_1 = node_num >> 1;
    constexpr device_t another_ID_2 = node_num >> 2;
    constexpr device_t another_ID_3 = discrete_sqrt(node_num) << 1;
    
}


//! @brief Tags used in the node storage.
namespace tags {
    //! @brief Color of the current node.
    struct node_color {};
    //! @brief Size of the current node.
    struct node_size {};
    //! @brief Shape of the current node.
    struct node_shape {};
    // ... add more as needed, here and in the tuple_store<...> option below

    // 
    struct node_scattered_db {};
    struct node_current_tick {};
    struct node_data_requested {}; // turns true only if the request or its response is "travelling" (i.e., after the spawn start and no longer the spawn has ended)
    struct node_last_requested_data {};
    struct node_requests_got {};
    struct node_requests_got_amount {};
    struct node_data_got {};
    struct node_responses_provided {};
    struct node_responses_provided_str {};
}

//! @brief The maximum communication range between nodes.
constexpr size_t communication_range = 100;

constexpr bool ALLOW_MULTIPLE_QUERIES = false;

constexpr real_t TIMEOUT_TOLERANCE = 0.25;  // 25% headroom above diameter estimate

//

using scattered_db_complex_t = std::map<s_db_key, s_db_data>;

using set_nodes_to_source_t = std::set<device_t>;

using spawn_res_query = tuple<
    scattered_db_query, // original query
    bool, // has the data?
    s_db_data // the actual data
>;
using spawn_res_response = scattered_db_response; // just an alias for future developments

// map< key , returned_thing , hash >
using spawn_res_query_map = std::unordered_map<scattered_db_query, spawn_res_query, common::hash<scattered_db_query> >;
using spawn_res_response_map = std::unordered_map<spawn_res_response, scattered_db_response, common::hash<spawn_res_response> >;

using provided_responses_k = tuple<
    device_t, // sender
    s_db_key,
    uint // "created at" time tick - valorized if ALLOW_MULTIPLE_QUERIES is true, set to 0 otherwise
>;
using responses_provided_t = std::unordered_map<provided_responses_k, scattered_db_response, common::hash<provided_responses_k> >;

/*
UTILITY FUNCTIONS
*/

FUN bool has_requested_data(ARGS, s_db_key const key) {
    return node.storage(tags::node_scattered_db{}).count(key) > 0;
}

FUN s_db_data get_data(ARGS, s_db_key const key) {
    return node.storage(tags::node_scattered_db{})[key];
}


/**
Dummy function to test if current node is enabled to ask for some data, or if its purpose
will always be the "forwarding node"
*/
FUN bool is_node_enabled_to_request_data(ARGS){
    return (node.uid == 7) // un nodo a caso ...
#if REQUESTER_AMOUNT_ >= 2
        || (node.uid == option::another_ID_1)
#endif
#if REQUESTER_AMOUNT_ >= 3
        || (node.uid == option::another_ID_2)
#endif
#if REQUESTER_AMOUNT_ >= 4
        || (node.uid == option::another_ID_3)
#endif
    ;
}

/**
Dummy function that check if current node has the need to request data.
It's "dummy" because it simply checks the timer's "current tick"
 */
FUN bool is_there_need_to_request_data(ARGS, uint current_tick){
    return is_node_enabled_to_request_data(CALL) //
        && ((current_tick % 11) == 0) // un intervallo di tempo a caso ...
        && (!(node.storage(tags::node_data_requested{})));
}


using update_key_data = tuple<
    uint, // the actual delta
    uint  // tick of last update (to avoid increments greater than 1)
>;
FUN s_db_key compute_key_query(ARGS, uint round_tick, bool can_fire_request_data){
    update_key_data delta_data = old(CALL, 
        static_cast<update_key_data>(make_tuple(0, 0)),
        [&](update_key_data const& old_update_data){
            if(can_fire_request_data &&
                (round_tick != get<1>(old_update_data))
            ){
                // an actual update may happen
                return static_cast<update_key_data>(make_tuple(get<0>(old_update_data) +1, round_tick));
            }
            return old_update_data;
        }
    );
    uint delta = get<0>(delta_data);
    auto md_id = (node.uid + delta);  // un nodo a caso ...
    while(md_id >= static_cast<s_db_key>(option::node_num)){ // module operator, but shorter
        md_id -= static_cast<s_db_key>(option::node_num);
    }
    return md_id;
}
FUN_EXPORT compute_key_query_t = export_list<update_key_data>;

/*
AGGREGATE FUNCTIONS
*/

/*
FUN device_t get_parent_spanning_tree(ARGS, real_t distance_from_source) { CALL
    return get<1>(
        min_hood(CALL,
            make_tuple(
                nbr(CALL, distance_from_source),
                node.nbr_uid()
            )
        )responses_provided_t
    );
}
EXPORT_FUN get_parent_spanning_tree_t = export_list<tuple<real_t, device_t>, device_t>;
*/

FUN void execute_scattered_db_query(ARGS, 
    uint round_tick,
    bool is_enabled_to_request
){ CODE
    /*
    // Every node uses this gradient for spawn routing.
    // In a production deployment, each requester would build its own gradient,
    real_t dist_from_requester = abf_distance(CALL, is_enabled_to_request);

    // ... spanning tree definition ...

    // device_t parent = get_parent_spanning_tree(CALL, dist_from_requester);
    
    // Collects the set of UIDs in this node's spanning-tree subtree toward
    // the root.  Used to determine INTERNAL routing status for the spawn.
    // ((routing sets along the tree))
    set_nodes_to_source_t nodes_to_source = sp_collection(CALL, 
        dist_from_requester, // distance from source
        set_nodes_to_source_t{node.uid}, // set for current node
        set_nodes_to_source_t{}, // set to accumulate into
        // accumulator / aggregator function
        [](set_nodes_to_source_t a, set_nodes_to_source_t b){ a.insert(b.begin(), b.end()); return a; }
    );
    */

    // part 1 - query : REQUESTER -> DATA HOLDER
    
    // ... define the query
    common::option<scattered_db_query> query; // starts by "absent / nullptr-containing". filled if a "spawn-process" needs to spawn
    bool can_fire_request_data = is_there_need_to_request_data(CALL, round_tick);
    s_db_key next_key_request = compute_key_query(CALL, round_tick, can_fire_request_data);
    can_fire_request_data &= (next_key_request != static_cast<s_db_key>(node.uid)) // can't look for/in myself!
        // AND do not already have the requested key
        && ! has_requested_data(CALL, next_key_request);
    if(can_fire_request_data) {
        //const bool allow_multiple_queries = false;
        query.emplace(
            next_key_request, // key
            node.uid, // requester
            round_tick, //
            node.current_time() //
        );
        // later, in the spawn, the "node_data_requested" storage field will be set to "true"
    }

    // ── Network diameter estimate (fully aggregate, outside spawns) ────────────────────
    // gossip_min elects the minimum UID as a globally consistent reference node.
    // abf_hops gives each node its hop distance from that reference.
    // gossip_max spreads the maximum hop distance → eccentricity of the reference.
    // diameter ≤ 2 × eccentricity(any node) (graph theory).
    // +1 guards against convergence lag on the first few rounds.
    device_t net_leader   = gossip_min(CALL, node.uid);
    hops_t   dist_ldr     = abf_hops(CALL, node.uid == net_leader);
    hops_t   eccentricity = gossip_max(CALL, dist_ldr);
    hops_t   timeout_hops = static_cast<hops_t>(
        static_cast<real_t>(2 * eccentricity) * (1.0f + TIMEOUT_TOLERANCE) + 1.0f
    );

    // ... run the spawn
    spawn_res_query_map query_res = spawn(CALL, [&](scattered_db_query const& message_query) {
        s_db_key key = message_query.key;
        bool is_requester = (node.uid == message_query.requester);
        bool has_data = has_requested_data(CALL, key);
        if (is_requester)
            node.storage(tags::node_last_requested_data{}) = message_query.to_string();
        // ── Flood frontier (unconditional) ────────────────────────────────────────────
        // abf_hops: hop distance from requester within the active spawn population.
        // gossip_max: how far the flood has spread (global max of hops_from_req).
        // When frontier > timeout_hops the whole reachable network has been searched.
        hops_t hops_from_req  = abf_hops(CALL, is_requester);
        hops_t flood_frontier = gossip_max(CALL, hops_from_req);
        bool   timed_out      = (flood_frontier > timeout_hops);
        // Unified termination: holder found OR data declared absent after timeout
        bool can_terminate = gossip(CALL, has_data || timed_out,
                                   [](bool x, bool y){ return x || y; });
        status s = has_data      ? status::terminated_output
                 : can_terminate ? status::terminated
                 :                 status::internal;
        if(!is_requester){
            if(has_data){
                node.storage(tags::node_size{}) = 25;
                node.storage(tags::node_shape{}) = shape::icosahedron;
            } else {
                node.storage(tags::node_size{}) = 20;
            }
        }
        return make_tuple(
            static_cast<spawn_res_query>(make_tuple(
                message_query,
                has_data,
                has_data ? get_data(CALL, key) : static_cast<s_db_data>(node.position())
            )),
            s
        );
    }, query);

    // part 2 - response : DATA HOLDER -> REQUESTER

    /*
    common::option<s_db_data> query_result;
    // if current node has a request (i.e., the map returned by the spawn has a "useful" value) ->
    // -> query_result.emplace( the answer's data -> node.storage(tags::node_scattered_db{})[ query.key ] );
    using reply_key_t = fcpp::tuple<device_t, s_db_data>;  // (querier_id, snapshot_data)
    
    bool reply_started = old(CALL, false, [&](bool prev){ return prev || q_res.count(my_key) > 0; });
    common::option<reply_key_t> reply;
    if (q_res.count(my_key) > 0 && !reply_started)
        reply.emplace(make_tuple(querier_id, node.position()));  // snapshot now
    */

    common::option<scattered_db_response> reply;
    // reply to all requests received ...
    uint greatest_requests_got_amount = old(CALL, static_cast<uint>(0),
        [&](uint x){
            return x > static_cast<uint>(query_res.size())
                ? x
                : static_cast<uint>(query_res.size());
        }
    );
    node.storage(tags::node_requests_got_amount{}) = greatest_requests_got_amount;

    // PHASE A — pure logic, no FCPP primitives.
    // Iterate query_res to decide which responses to inject; collect them into a vector.
    // Calling spawn inside this loop would be wrong: nodes with 0 entries would call it
    // 0 times while nodes with N entries call it N times, breaking trace synchronization.
    std::vector<scattered_db_response> responses_to_inject;
#if __cplusplus <= 201402L
    // C++14 and older
    for (auto const& kv : query_res) {
        scattered_db_query k = kv.first;
        spawn_res_query    v = kv.second;
#else
    // C++17 and newer
    for (auto const& [k, v] : query_res) {
#endif
        node.storage(tags::node_requests_got{})[std::to_string(k.key)] = k.to_string();
        device_t sender          = k.requester;
        s_db_key requested_key   = k.key;
        uint response_created_at = ALLOW_MULTIPLE_QUERIES ? round_tick : 0;
        bool has_data            = get<1>(v);
        s_db_data actual_data    = get<2>(v);

        provided_responses_k key_already = make_tuple(sender, requested_key, response_created_at);
        if (has_data &&
            node.storage(tags::node_responses_provided{}).count(key_already) == 0) {

            scattered_db_response resp(requested_key, actual_data,
                                       sender, node.uid, round_tick, node.current_time());
            node.storage(tags::node_responses_provided{})[key_already] = resp;
            node.storage(tags::node_responses_provided_str{})[std::to_string(requested_key)] = resp.to_string();
            responses_to_inject.push_back(resp);
        }
    }

    // PHASE B — single spawn call, outside any loop.
    // Every node reaches this point exactly once per round regardless of query_res size,
    // keeping the CALL trace counter synchronized across the network.
    // Each entry in responses_to_inject starts a separate spawn process.
    spawn_res_response_map response_res = spawn(CALL, [&](scattered_db_response const& resp) {
        bool is_requester = (node.uid == resp.requester);
        bool is_holder    = (node.uid == resp.holder);
        // Per-spawn tree rooted at holder — avoids Voronoi fragmentation with multiple requesters.
        // requester in subtree_from_holder ↔ this node is on the holder→requester path.
        real_t dist_from_holder = bis_distance(CALL, is_holder, 1, communication_range);
        set_nodes_to_source_t subtree_from_holder = sp_collection(CALL,
            dist_from_holder,
            set_nodes_to_source_t{node.uid}, set_nodes_to_source_t{},
            [](set_nodes_to_source_t a, set_nodes_to_source_t b){
                a.insert(b.begin(), b.end()); return a;
            }
        );
        bool inpath = subtree_from_holder.count(resp.requester) > 0;
        status s = is_requester ? status::terminated_output
                 : inpath       ? status::internal : status::border;
        if (is_requester) {
            node.storage(tags::node_data_requested{}) = false;
            node.storage(tags::node_color{}) = color(BLACK);
        } else {
            node.storage(tags::node_shape{}) = inpath ? shape::sphere : shape::cube;
        }
        return make_tuple(resp, s);
    }, responses_to_inject);

    // PHASE C — consume responses, pure logic, no FCPP primitives.
#if __cplusplus <= 201402L
    // C++14 and older
    for (auto const& kv : response_res) {
        scattered_db_response k_r = kv.first;
        scattered_db_response v_r = kv.second;
#else
    // C++17 and newer
    for (auto const& [k_r, v_r] : response_res) {
#endif
        s_db_data response_data = v_r.data;
        device_t requester      = v_r.requester;
        s_db_key request_key    = v_r.key;
        if (node.uid == requester) {
            node.storage(tags::node_data_got{})[k_r.to_string()] = response_data;
            if ( has_requested_data(CALL, request_key) ) {
                node.storage(tags::node_scattered_db{})[request_key] = response_data;
            }
            node.storage(tags::node_data_requested{}) = false;
        } else {
            node.storage(tags::node_last_requested_data{}) = "AM I NOT THE REQUESTER? <" +
                std::to_string(node.uid) + " ; " + std::to_string(requester) + ">";
        }
    }
}
FUN_EXPORT execute_scattered_db_query_t = export_list<
    compute_key_query_t,
    device_t,                                         // gossip_min<device_t> outside spawns
    hops_t,                                           // abf_hops + gossip_max (outside + inside query spawn)
    bool,                                             // gossip<bool> inside query spawn
    uint,
    bis_distance_t,                                   // inside response spawn
    sp_collection_t<real_t, set_nodes_to_source_t>,  // inside response spawn
    spawn_t<scattered_db_query, status>,
    spawn_t<spawn_res_response, status>
>;

//
//



FUN void initialize_scattered_db(ARGS){ CODE
    auto scattered_database_result = // new_vector_coprime_IDs(CALL);
        old(CALL,
            scattered_db_complex_t{}, // default at round 0
            [&](scattered_db_complex_t const& old_data){
                scattered_db_complex_t new_data = new_coprime_nbr_data(CALL, [&](node_t const& neighbor){ return static_cast<s_db_data>(neighbor.position()); });
                // keep the first initialization, i.e. never update iit
                return old_data.empty() ? new_data : (node.storage(tags::node_scattered_db{})); 
            }
        );
    node.storage(tags::node_scattered_db{}) = scattered_database_result;
}
FUN_EXPORT initialize_scattered_db_t = export_list<scattered_db_complex_t, new_coprime_nbr_data_t, s_db_data>;

// @brief Main function.
MAIN() {
    //
    // import tag names in the local scope.
    using namespace tags;
    
    uint round_tick = old(CALL, 0, [&](uint a){
        return a+1;
    });
    //
    node.storage(node_current_tick{}) = round_tick;
    
    // initialization
    initialize_scattered_db(CALL);
    
    // THE ACTUAL CODE
        
    /*
    in futuro, ci saranno più nodi contemporaneamente a fare richieste -> ciascuno con il proprio ... spawn? forse?
    */
    bool is_enabled_to_request = is_node_enabled_to_request_data(CALL);


    // usage of node physics
    //node.velocity() = -node.position()/communication_range;

    auto constexpr maximum_db_size = 15.0f;
    // usage of node storage
    node.storage(node_size{}) = is_enabled_to_request ? 30 : 10;
    auto constexpr hue_scale = 360.0f / maximum_db_size; // option::node_num;
    node.storage(node_color{}) = //
        color::hsva( static_cast<real_t>(node.storage(node_scattered_db{}).size()) * hue_scale, 1, 1);

    if(is_enabled_to_request){
        node.storage(node_shape{}) = shape::star; // is_enabled_to_request ? shape::star : shape::sphere; // icosahedron
    } else {
        node.storage(node_shape{}) = shape::tetrahedron;
    }

    // DO THE THING

    execute_scattered_db_query(CALL,
        round_tick,
        is_enabled_to_request
    );

        
}
    
//! @brief Export types used by the main function (update it when expanding the program).
FUN_EXPORT main_t = export_list<
    initialize_scattered_db_t,
    uint,
    // bool, // it's not actually shared across the nodes
    new_coprime_nbr_data_t, // new_vector_coprime_IDs_t,
    old_t<scattered_db_complex_t>, // old_t<new_vector_coprime_IDs_t>
    scattered_db_complex_t, 
    execute_scattered_db_query_t
>;

} // namespace coordination

// [SYSTEM SETUP]

//! @brief Namespace for component options.
namespace option {

//! @brief Import tags to be used for component options.
using namespace component::tags;
//! @brief Import tags used by aggregate functions.
using namespace coordination::tags;


//! @brief Description of the round schedule.
using round_s = sequence::periodic<
    distribution::interval_n<times_t, 0, 1>,    // uniform time in the [0,1] interval for start
    distribution::weibull_n<times_t, 10, 1, 10> // weibull-distributed time for interval (10/10=1 mean, 1/10=0.1 deviation)
>;
//! @brief The sequence of network snapshots (one every simulated second).
using log_s = sequence::periodic_n<1, 0, 1>;
//! @brief The sequence of node generation events (node_num devices all generated at time 0).
using spawn_s = sequence::multiple_n<coordination::option::node_num, 0>;
//! @brief The distribution of initial node positions (random in a 500x500 square).
using rectangle_d = distribution::rect_n<1, 0, 0, coordination::option::network_width, coordination::option::network_height>;
//! @brief The contents of the node storage as tags and associated types.
using store_t = tuple_store<
    node_color,                 color,
    node_size,                  double,
    node_shape,                 shape
    //
    , node_scattered_db,        coordination::scattered_db_complex_t // vector_coprime_IDs_t

    , node_data_requested,      bool
    , node_last_requested_data, std::string // scattered_db_query
    , node_current_tick,        uint
    , node_requests_got,        std::map<std::string, std::string>
    , node_requests_got_amount, uint
    , node_data_got,            std::map<std::string, s_db_data> // s_db_data
    , node_responses_provided,  coordination::responses_provided_t 
    , node_responses_provided_str, std::map<std::string, std::string> 
>;
//! @brief The tags and corresponding aggregators to be logged (change as needed).
using aggregator_t = aggregators<
    node_size,                  aggregator::mean<double>
    //
    //, node_nbr_amount,          aggregator::mean<int>
>;

//! @brief The general simulation options.
DECLARE_OPTIONS(list,
    parallel<true>,      // multithreading enabled on node rounds
    synchronised<false>, // optimise for asynchronous networks
    program<coordination::main>,   // program to be run (refers to MAIN above)
    exports<coordination::main_t>, // export type list (types used in messages)
    retain<metric::retain<2,1>>,   // messages are kept for 2 seconds before expiring
    round_schedule<round_s>, // the sequence generator for round events on nodes
    log_schedule<log_s>,     // the sequence generator for log events on the network
    spawn_schedule<spawn_s>, // the sequence generator of node creation events on the network
    store_t,       // the contents of the node storage
    aggregator_t,  // the tags and corresponding aggregators to be logged
    init<
        x,      rectangle_d // initialise position randomly in a rectangle for new nodes
    >,
    dimension<coordination::option::dim>, // dimensionality of the space
    connector<connect::fixed<coordination::option::node_num, 1, coordination::option::dim>>, // connection allowed within a fixed comm range
    shape_tag<node_shape>, // the shape of a node is read from this tag in the store
    size_tag<node_size>,   // the size  of a node is read from this tag in the store
    color_tag<node_color>  // the color of a node is read from this tag in the store
);

} // namespace option

} // namespace fcpp


//! @brief The main function.
int main() {
    using namespace fcpp;
    
    //! @brief The network object type (interactive simulator with given options).
    using net_t = component::interactive_simulator<option::list>::net;
    //! @brief The initialisation values (simulation name).
    auto init_v = common::make_tagged_tuple<option::name>("Exercises");
    //! @brief Construct the network object.
    net_t network{init_v};
    //! @brief Run the simulation until exit.
    network.run();
    return 0;
}

// cd fcpp-exercises
// ./make.sh gui run -O scattered_database
