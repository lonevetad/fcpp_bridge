// Copyright © 2021 Giorgio Audrito. All Rights Reserved.

#ifndef REQUESTER_AMOUNT_
#define REQUESTER_AMOUNT_ 1
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

/*
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
*/



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

    //! @brief The maximum communication range between nodes.
    constexpr size_t communication_range = 100;

    constexpr uint PULSE_PERIODICITY = 11; // after each X ticks, it pulses

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
    struct node_current_tick {};
    
    struct node_can_send_data {};
    struct node_last_tick_sent_data {};
    struct node_can_receive_data {};
    struct node_data_sent {};
    struct node_data_received {};
    struct node_ticks_status {};
}

//


/*
UTILITY FUNCTIONS
*/

std::string tick_status_to_str(uint tick_status){
    char buffer[32];
    char* p = buffer + 32;
    do
    {
        *--p = '0' + (tick_status & 1);
    } while (tick_status >>= 1);
    return std::string(p, buffer + 32);
}

bool check_id_enabled_to_pulse(device_t node_id){
    return (node_id == 7) // un nodo a caso ...
#if REQUESTER_AMOUNT_ >= 2
        || (node_id == option::another_ID_1)
#endif
#if REQUESTER_AMOUNT_ >= 3
        || (node_id == option::another_ID_2)
#endif
#if REQUESTER_AMOUNT_ >= 4
        || (node_id == option::another_ID_3)
#endif
    ;
}

/**
Dummy function to test if current node is enabled to ask for some data, or if its purpose
will always be the "forwarding node"
*/
FUN bool is_node_enabled_to_pulse(ARGS){
    return check_id_enabled_to_pulse(node.uid);
}

/**
Dummy function that check if current node has the need to request data.
It's "dummy" because it simply checks the timer's "current tick"
 */
FUN bool is_there_need_to_pulse(ARGS, uint current_tick){
    return is_node_enabled_to_pulse(CALL) //
        && ((current_tick % option::PULSE_PERIODICITY) == 0)
        //&& can_send_data(CALL)
        ;
}

/*
AGGREGATE FUNCTIONS
*/


//
//

using key_to_send = tuple<
    device_t, // sender
    uint // tick/clock of the sender
>;
// D is embedded in the key so every spawn participant can access the pulsed data.
template<typename D>
using key_data_t = tuple<device_t, uint, D>;

template<typename T>
using result_data_t = tuple<device_t, uint, T>;

template<typename D, typename T>
using pulse_map_t = std::unordered_map<key_data_t<D>, result_data_t<T>, common::hash<key_data_t<D>>>;

GEN(D, T, F,
    BOUND(F, T(node_t&, D))
)
pulse_map_t<D, T> pulse_data(ARGS,
    uint current_tick, bool is_source, bool can_pulse_now, D data_to_pulse, bool can_output,
    //CO&& can_output,
    T zero_value, F&& result_supplier_to_receiver, // core
    uint additional_ticks_in_internal, uint additional_ticks_in_border // config
) { CODE
    constexpr uint BITS_TO_SHIFT = 4; // the "status" enum has 9 entries -> the first 4 bits are occupied
    constexpr uint STATUS_MASK = (1 << (BITS_TO_SHIFT + 1)) - 1;
    constexpr uint MAX_TICKS = (1<<(31-BITS_TO_SHIFT)) - 1;
    uint ati = (additional_ticks_in_internal > MAX_TICKS) ? MAX_TICKS : additional_ticks_in_internal;
    uint atb = (additional_ticks_in_border > MAX_TICKS) ? MAX_TICKS : additional_ticks_in_border;

    common::option<key_data_t<D>> query_key;
    if(is_source && can_pulse_now &&
        node.storage(tags::node_last_tick_sent_data{}) != current_tick
    ){
        query_key.emplace(make_tuple(node.uid, current_tick, data_to_pulse));
        node.storage(tags::node_last_tick_sent_data{}) = current_tick;
        node.storage(tags::node_data_sent{}) = data_to_pulse;
    }
    return spawn(CALL,
        [&](key_data_t<D> const& message_query){
            D data_pulsed = get<2>(message_query);

            uint ticks_left__status = old(CALL,
                can_output
                    ? (uint)status::terminated_output
                    : (((ati + 1) << BITS_TO_SHIFT) | (uint)status::internal),
                [&](uint current__ticks_left__status){
                    uint ticks_left = current__ticks_left__status >> BITS_TO_SHIFT;
                    status current_status = static_cast<status>(current__ticks_left__status & STATUS_MASK);
                    if(current_status == status::terminated || current_status == status::terminated_output){
                        return current__ticks_left__status;
                    }
                    if(ticks_left <= 1){
                        ticks_left = 0;
                        if(current_status == status::internal){
                            current_status = status::border;
                            ticks_left = atb;
                        } else {
                            assert(current_status == status::border);
                            current_status = status::terminated;
                        }
                    }else{
                        ticks_left--;
                    }
                    return (ticks_left << BITS_TO_SHIFT) | (uint)current_status;
                }
            );
            status curr_status = static_cast<status>(ticks_left__status & STATUS_MASK);
            assert(can_output == (curr_status == status::terminated_output));
            node.storage(tags::node_ticks_status{}) = to_string(curr_status); // tick_status_to_str(ticks_left__status); //(ticks_left__status >> BITS_TO_SHIFT);
            // set the color
            if(is_source){
                node.storage(tags::node_color{}) = can_pulse_now ? color(BLACK) : color(PURPLE);
            } else {
                if(can_output){
                    node.storage(tags::node_color{}) = color(BLUE);
                } else if(curr_status == status::terminated){
                    node.storage(tags::node_color{}) = color(LIGHT_BLUE);
                } else if(curr_status == status::internal){
                    node.storage(tags::node_color{}) = color(GREEN);
                } else { // border
                    node.storage(tags::node_color{}) = color(YELLOW);
                }
            }

            return make_tuple(
                can_output
                    ? make_tuple(get<0>(message_query), get<1>(message_query), result_supplier_to_receiver(node, data_pulsed))
                    : make_tuple(device_t{}, uint{}, zero_value),
                curr_status
            );
        },
        query_key
    );
}

GEN_EXPORT(D, T) pulse_data_t = export_list<
    uint,
    T,
    device_t,
    spawn_t<key_data_t<D>, status>
>;

using data_to_output_t = vec<option::dim>;
using data_to_pulse_t = device_t;
using spawn_res_t = tuple<device_t, uint, data_to_output_t>;

// @brief Main function.
MAIN() {
    //
    // import tag names in the local scope.
    using namespace tags;
    node.storage(node_color{}) = color(WHITE); // reset, to clean up previous calculations
    
    uint round_tick = old(CALL, 0, [&](uint a){
        return a+1;
    });
    //
    node.storage(node_current_tick{}) = round_tick;
    
    data_to_output_t data_zero_value = old(CALL, data_to_output_t{0.0, 0.0}, [&](data_to_output_t x) { return x; });
    
    // THE ACTUAL CODE
    bool is_source = is_node_enabled_to_pulse(CALL);
    bool can_pulse_now = is_there_need_to_pulse(CALL, round_tick);
    bool can_output = check_id_enabled_to_pulse(node.uid + 1);

    data_to_pulse_t dtp = static_cast<data_to_pulse_t>(node.uid);

    // usage of node physics
    //node.velocity() = -node.position()/option::communication_range;

    // usage of node storage
    node.storage(node_size{}) = can_pulse_now ? 30 : (is_source ? 20 : 10);
    /*
    auto constexpr maximum_db_size = 15.0f;
    auto constexpr hue_scale = 360.0f / maximum_db_size; // option::node_num;
    node.storage(node_color{}) = //
    color::hsva( static_cast<real_t>(node.storage(node_scattered_db{}).size()) * hue_scale, 1, 1);
    
    */
    if(can_pulse_now){
        node.storage(node_shape{}) = shape::star; // is_enabled_to_request ? shape::star : shape::sphere; // icosahedron
    } else if(is_source){
        node.storage(node_shape{}) = shape::tetrahedron;
    } else if(can_output){
        node.storage(node_shape{}) = shape::cube;
    } else {
        node.storage(node_shape{}) = shape::sphere;
    }
    node.storage(node_can_send_data{}) = can_pulse_now;
    node.storage(node_can_receive_data{}) = can_output;
    

    // DO THE THING

    constexpr uint additional_ticks_in_internal = 3; //5;
    constexpr uint additional_ticks_in_border = 1; // 3;

    pulse_map_t<data_to_pulse_t, data_to_output_t> res = pulse_data(CALL,
        round_tick, is_source, can_pulse_now, dtp, can_output,
        /*
        [&](device_t node_id, data_to_pulse_t dtp_got, uint tick){
            return check_id_enabled_to_pulse(node.uid + 1); // just one random node
        },
        */
        data_zero_value,
        [&](node_t& current_node, data_to_pulse_t dtp_got){
            return current_node.position();
        },
        additional_ticks_in_internal, additional_ticks_in_border
    );

    //std::vector<spawn_res_t> resps_got;
    for (pulse_map_t<data_to_pulse_t, data_to_output_t>::value_type const& kv : res) {
        key_data_t<data_to_pulse_t> const k = kv.first;
        spawn_res_t const v = kv.second;
        //resps_got.push_back(v);
        node.storage(tags::node_data_received{})[get<0>(k)] = v;
    }
    //node.storage(tags::node_data_received{}) = resps_got;
}
    
//! @brief Export types used by the main function (update it when expanding the program).
FUN_EXPORT main_t = export_list<
    uint,
    data_to_output_t,
    pulse_data_t<data_to_pulse_t, data_to_output_t>
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

    , node_current_tick,        uint
    , node_can_send_data,       bool
    , node_can_receive_data,    bool
    , node_last_tick_sent_data, uint
    , node_data_sent,           coordination::data_to_pulse_t
    , node_data_received,       std::map<device_t, coordination::spawn_res_t>
    , node_ticks_status,        std::string
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
//  ./make.sh gui run -O pulse
