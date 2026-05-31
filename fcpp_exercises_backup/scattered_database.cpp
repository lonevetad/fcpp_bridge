// Copyright © 2021 Giorgio Audrito. All Rights Reserved.

// CREATO A PARTIRE DAL PROGETTO "fcpp-exercises" PER STUDIARE

/**
 * @file exercises.cpp
 * @brief Quick-start aggregate computing exercises.
 */

// [INTRODUCTION]
//! Importing the FCPP library.
#include "lib/fcpp.hpp"
#include "run/shared.hpp"
#include "run/storage_init.hpp"


//! @brief Struct representing a data to be retrieved from a scattered database.
struct scattered_db_query_data {
    //! @brief whether the data is present or not
    bool is_data_present;
    //! @brief THE ACTUAL DATA - in this exercise, is the related node's position
    fcpp::vec<2> data;
    //! @brief the database KEY - in this exercise, the ID of the node whose position is asked for in the current query
    fcpp::device_t key;
    //! @brief Receiver UID, the device/node who started this query
    fcpp::device_t requester;
    //! @brief Creation timestamp, but in "ticks".
    uint created_at_tick;
    //! @brief Creation timestamp.
    fcpp::times_t time;
    //! @brief counter, tracking how many times the device/node has asked for _some_ data
    // uint;

    //! @brief Empty constructor.
    scattered_db_query_data() = default;

    //! @brief Member constructor.
    scattered_db_query_data(
        bool is_data_present,
        vec<2> data,
        fcpp::device_t key,
        fcpp::device_t requester,
        uint created_at_tick,
        fcpp::times_t time
    ) : is_data_present(is_data_present), data(data), key(key), requester(requester), created_at_tick(created_at_tick), time(time) {}

    //! @brief Equality operator.
    bool operator==(scattered_db_query_data const& m) const {
        return is_data_present == m.is_data_present
            and data == m.data
            and key == m.key
            and requester == m.requester
            and created_at_tick == created_at_tick
            and time == m.time;
    }

    static size_t hash(vec<2> data_to_hash){
        constexpr size_t fields_count = 2;
        constexpr size_t offs = sizeof(size_t)*CHAR_BIT/fields_count;
        return (size_t(get<1>(data_to_hash)) << offs) | size_t(get<0>(data_to_hash));
    }

    //! @brief Hash computation.
    size_t hash() const {
        constexpr size_t fields_count = 6;
        constexpr size_t offs = sizeof(size_t)*CHAR_BIT/fields_count;
        return  ((size_t(time) << (5*offs))
            | (size_t(created_at_tick) << (offs << 2))
            | ((size_t(requester) << (3*offs))
            | ((size_t(key) << (offs << 1))
            | hash(data)
            | size_t(is_data_present);
    }

    //! @brief Serialises the content from/to a given input/output stream.
    template <typename S>
    S& serialize(S& s) {
        return s & is_data_present & data & key & requester & created_at_tick & time;
    }

    //! @brief Serialises the content from/to a given input/output stream (const overload).
    template <typename S>
    S& serialize(S& s) const {
        return s << is_data_present << data << key << requester << created_at_tick << time;
    }
};


namespace std {
    //! @brief Hasher object for the scattered_db_query_data struct.
    template <>
    struct hash<scattered_db_query_data> {
        //! @brief Produces an hash for a scattered_db_query_data, combining its instance variables into a size_t.
        size_t operator()(scattered_db_query_data const& m) const {
            return m.hash();
        }
    };
}




/**
 * @brief Namespace containing all the objects in the FCPP library.
 */
namespace fcpp {

//! @brief Namespace containing the libraries of coordination routines.
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
    struct node_data_got {};
}

//! @brief The maximum communication range between nodes.
constexpr size_t communication_range = 100;

using scattered_db_complex_t = std::map<device_t, vec<2>>;

using set_nodes_to_source_t = std::set<device_t>:

/*
UTILITY FUNCTIONS
*/

/**
Dummy function to test if current node is enabled to ask for some data, or if its purpose
will always be the "forwarding node"
*/
FUN bool is_node_enabled_to_request_data(ARGS){
    return node.uid == 7; // un nodo a caso ...
}

/**
Dummy function that check if current node has the need to request data.
It's "dummy" because it simply checks the timer's "current tick"
 */
FUN bool is_there_need_to_request_data(ARGS, uint current_tick){
    return is_node_enabled_to_request_data(CALL) //
        && ((current_tick % 9) == 0) // un intervallo di tempo a caso ...
        && (!(node.storage(tags::node_data_requested{})));
}



FUN device_t compute_key_query(ARGS){
    auto md_id = (node.uid + 1);  // un nodo a caso ...
    if(md_id >= static_cast<device_t>(option::node_num)){ // module operator, but shorter
        md_id = 0;
    }
    return md_id;
}

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
        )
    );
}
EXPORT_FUN get_parent_spanning_tree_t = export_list<tuple<real_t, device_t>, device_t>;
*/

FUN scattered_db_query_data scattered_db_query(ARGS, 
    uint round_tick,
    bool is_enabled_to_request
){ CODE


    //
    // COMPUTATION OF THE DATA RETRIEVAL
    //

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
        {node.uid}, // set for current node
        {}, // set to accumulate into
        // accumulator / aggregator function
        [](auto a, auto b){ return a | b; }
    );

    // START THE SPAWN PART

    // define the query
    common::option<scattered_db_query_data> query; // starts by "absent / nullptr-containing". filled if a "spawn-process" needs to spawn
    common::option
    if(is_there_need_to_request_data(CALL, round_tick)) {
        query.emplace(
            false, // data NOT present (at the beginning of the spawned process's execution)
            compute_key_query(CALL), // key
            node.uid, // requester
            round_tick, //
            node.current_time() //
        );
        // later, in the spawn, the "node_data_requested" storage field will be set to "true"
    }


    //

    ;
}
FUN_EXPORT scattered_db_query_data_t = export_list<
    // get_parent_spanning_tree_t,
    real_t,
    set_nodes_to_source_t,
    sp_collection_t<real_t, set_nodes_to_source_t>, 
    device_t,
    spawn_t<>,
    spawn_t<message, status>
>;

//
//

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
    
    auto scattered_database_result = // new_vector_coprime_IDs(CALL);
        old(CALL,
            scattered_db_complex_t{}, // default at round 0
            [&](scattered_db_complex_t const& old_data){
                auto new_data = new_coprime_nbr_data(CALL, [&](node_t const& neighbor){ return neighbor.position(); })
                // keep the first initialization, i.e. never update iit
                return old_data.empty() ? new_data : old_data; 
            }
        );
    node.storage(node_scattered_db{}) = scattered_database_result;
    
    // THE ACTUAL CODE
        
    /*
    in futuro, ci saranno più nodi contemporaneamente a fare richieste -> ciascuno con il proprio ... spawn? forse?
    */
    bool is_enabled_to_request = is_node_enabled_to_request_data(CALL);

    auto xxx = scattered_db_query_data(CALL,
        round_tick,
        is_enabled_to_request
    );


    // usage of node physics
    //node.velocity() = -node.position()/communication_range;

    // usage of node storage
    node.storage(node_size{}) = is_enabled_to_request ? 20 : 10;
    auto const hue_scale = 360.0f / 5; // option::node_num;
    node.storage(node_color{}) = //
        color::hsva( static_cast<real_t>(node.storage(node_scattered_db{}).size()) * hue_scale, 1, 1);

    node.storage(node_shape{}) = is_enabled_to_request ? shape::star : shape::sphere; // icosahedron
        
}
    
//! @brief Export types used by the main function (update it when expanding the program).
FUN_EXPORT main_t = export_list<
    uint,
    // bool, // it's not actually shared across the nodes
    new_coprime_nbr_data_t, // new_vector_coprime_IDs_t,
    old_t<scattered_db_complex_t>, // old_t<new_vector_coprime_IDs_t>
    scattered_db_complex_t, 
    scattered_db_query_data_t
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
    , node_scattered_db,        scattered_db_complex_t // vector_coprime_IDs_t

    , node_data_requested,      bool
    , node_current_tick,        uint
    , node_data_got,            device_t
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

// ./make.sh gui run -O scattered_database
