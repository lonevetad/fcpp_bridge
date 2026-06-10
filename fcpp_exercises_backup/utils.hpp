

#ifndef UTILS_STUFF_H_
#define UTILS_STUFF_H_
//! Importing the FCPP library.
#include "lib/fcpp.hpp"


//! @brief Minimum number whose square is at least n.
constexpr size_t discrete_sqrt(size_t n) {
    size_t lo = 0, hi = n, mid = 0;
    while (lo < hi) {
        mid = (lo + hi)/2;
        if (mid*mid < n) lo = mid+1;
        else hi = mid;
    }
    return lo;
}

#endif