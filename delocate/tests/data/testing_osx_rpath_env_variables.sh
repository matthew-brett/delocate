#!/bin/bash

# Demonstrate how OSX uses environment variables to resolve @rpath
# entries (and how it searches for dynamic libraries in general)
# At time of writing, the most recent documentation Apple provides on
# how this is supposed to work appears to be here:
#
# https://developer.apple.com/library/content/documentation/DeveloperTools/Conceptual/DynamicLibraries/100-Articles/DynamicLibraryUsageGuidelines.html
#
# To summarize that:
# Case 1:
# GIVEN a library libc with an @rpath entry that refers to another
#     library libb:
# WHEN libc is referred to in such a way that the path to it does
#     not include any directories
# AND libb can't be found because @rpath isn't set, or is set
#     incorrectly,
# THEN you can cause libb to be found by setting any one of
#     LD_LIBRARY_PATH
#     DYLD_LIBRARY_PATH
#     DYLD_FALLBACK_LIBRARY_PATH
#     so that it causes libc's @rpath entry to resolve correctly.
#
# Alternatively:
# Case 2:
# WHEN libc is referred to in such a way that the path to it *does*
#     include a directory,
# AND libb can't be found because @rpath isn't set, or is set
#     incorrectly,
# THEN you can cause libb to be found by setting any one of
#     DYLD_LIBRARY_PATH
#     DYLD_FALLBACK_LIBRARY_PATH
#     so that it causes libc's @rpath entry to resolve correctly.
#     (note that that list does not contain LD_LIBRARY_PATH)

# We'll demonstrate this using the three libaries liba, b, and c that
# ship with the tests, along with the "test-libs" binary.

# We're going to be manipulating the location of the test-lib script
# so that it either contains directory paths when we call it, or it
# doesn't, so it's important that we run this script from the
# directory that contains test-lib
if [ ! -x ./test-lib ];
then
    echo "The test-lib script must be accessible from this directory"
    exit 1
fi

run_expect_success() {
    if ! $1;
    then
	echo "Unexpected failure of call to $1"
	exit 1
    fi
}

run_expect_failure() {
    if $1;
    then
	echo "Unexpected success of call to $1"
	exit 1
    fi
}

set_var_expect_success() {
    export $1=$2
    run_expect_success $3
    unset $1
}

set_var_expect_failure() {
    export $1=$2
    run_expect_failure $3
    unset $1
}

# Turn on output of all the shell commands so we can see what's
# happening
set -x

# Confirm that test-lib works
echo "Running test-lib without making any changes"
run_expect_success "./test-lib"

# Case 1 -- path to library does not include a directory
# Change libc to refer to libb using @rpath, and re-run test-lib
echo "Modifying libc to refer to libb using @rpath"
install_name_tool -change libb.dylib @rpath/libb.dylib libc.dylib
otool -L libc.dylib
echo "Calling test-lib again -- you should see an error about" \
     "failing to find libb"
run_expect_failure "./test-lib"
echo "Calling test-lib with various environment variables set"
echo "All of these should work successfully"
set_var_expect_success LD_LIBRARY_PATH . ./test-lib
set_var_expect_success DYLD_LIBRARY_PATH . ./test-lib
set_var_expect_success DYLD_FALLBACK_LIBRARY_PATH . ./test-lib
echo "Resetting libc to its original state"
install_name_tool -change @rpath/libb.dylib libb.dylib libc.dylib

# Case 2 -- path to library does include a directory
echo "test-lib should still work normally"
run_expect_success ./test-lib
echo "Change libc to have an @rpath just like before"
install_name_tool -change libb.dylib @rpath/libb.dylib libc.dylib
otool -L libc.dylib
echo "...but now move everything into a subdirectory"
mkdir subdir
mv test-lib liba.dylib libb.dylib libc.dylib subdir
echo "test-lib should be broken like it was before"
run_expect_failure ./subdir/test-lib
echo "...but we can't use LD_LIBRARY_PATH to make things work now"
set_var_expect_failure LD_LIBRARY_PATH subdir ./subdir/test-lib
echo "This is because the path to test-lib contains a directory"
echo "DYLD_LIBRARY_PATH and DYLD_FALLBACK_LIBRARY_PATH still work"
set_var_expect_success DYLD_LIBRARY_PATH subdir ./subdir/test-lib
set_var_expect_success DYLD_FALLBACK_LIBRARY_PATH subdir ./subdir/test-lib
mv subdir/* .
install_name_tool -change @rpath/libb.dylib libb.dylib libc.dylib
rmdir subdir

echo "Finally, the simple case -- no @rpath necessary"
mkdir subdir
mv test-lib liba.dylib libb.dylib libc.dylib subdir
echo "We can't call test-lib from here because it can't find" \
    "its libraries"
run_expect_failure subdir/test-lib
echo "And we can't make it work using LD_LIBRARY_PATH"
set_var_expect_failure LD_LIBRARY_PATH subdir subdir/test-lib
echo "But the DYLD paths still work fine"
set_var_expect_success DYLD_LIBRARY_PATH subdir subdir/test-lib
set_var_expect_success DYLD_FALLBACK_LIBRARY_PATH subdir subdir/test-lib
mv subdir/* .
rmdir subdir

echo "As an extra, we'll demonstrate how OSX resolves library" \
    "references containing directories"
# This is an additional part of the documentation not covered above
# The order OSX will try and find a library dependency when it has a
# directory in the name is:
# 1. Search for the basename of the library on DYLD_LIBRARY_PATH
# 2. Search for the library using its full path
# 3. Search for its basename on DYLD_FALLBACK_LIBRARY_PATH
mkdir subdir
cp libb.dylib subdir
echo "We have two libb dylibs now -- one in the current working dir" \
    "and one in subdir"
echo "Start by updating libc to use an absolute path to libb"
install_name_tool -change libb.dylib $(pwd)/libb.dylib libc.dylib
otool -L libc.dylib
echo "test-lib should work fine"
run_expect_success ./test-lib
echo "If we turn on DYLD_PRINT_LIBRARIES we can confirm the library" \
    "that test-lib is loading"
export DYLD_PRINT_LIBRARIES=YES
# DYLD_PRINT_LIBRARIES outputs to stderr, so we need to redirect that
# to stdout so that we can grep it
./test-lib 2>&1 | grep libb
echo "If we set DYLD_LIBRARY_PATH to point to subdir we should load" \
    "that libb first"
set_var_expect_success DYLD_LIBRARY_PATH subdir ./test-lib 2>&1 | grep libb
echo "Finally, setting DYLD_FALLBACK_LIBRARY path does nothing"
set_var_expect_success DYLD_FALLBACK_LIBRARY_PATH subdir ./test-lib 2>&1 | grep libb
rm -rf subdir
install_name_tool -change $(pwd)/libb.dylib libb.dylib libc.dylib

echo "Demonstration completed successfully"
