#ifndef SHARED_EXERCISES__
#define SHARED_EXERCISES__

//! Importing the FCPP library.
#include "lib/fcpp.hpp"

/**
 * @brief Namespace containing all the objects in the FCPP library.
 */
namespace fcpp {

    //! @brief Dummy ordering between positions (allows positions to be used as secondary keys in ordered tuples).
    template <size_t n>
    bool operator<(vec<n> const& v1, vec<n> const& v2) {
        int i = 0;
        while(i < n){
            auto e1 = v1[i];
            auto e2 = v2[i]; 
            if(e1 > e2){
                return false;
            } else if(e1 < e2){
                return true;
            } // else: identical
            i++;
        }
        return false;
    }

    template <typename node_t, typename F, typename = common::if_signature<F, common::unit(device_t)>>
    common::unit for_each_nbr(node_t& node, trace_t call_point, F&& nbr_consumer) {
        return coordination::fold_hood(node, call_point,
            [&](device_t nbr_id, common::unit, common::unit) -> common::unit {
                nbr_consumer(nbr_id);
                return {};
            },
            common::unit{}, common::unit{});
    }
    FUN_EXPORT for_each_nbr_t = export_list<device_t, common::unit>; // even F?

}

#endif