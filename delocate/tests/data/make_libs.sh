#!/bin/bash
# Create libs used for testing
# Run in directory containing this file
# With thanks to https://dev.lsstcorp.org/trac/wiki/LinkingDarwin
# I ran this on a Snow Leopard machine with CXX=g++ ./make_libs.sh

if [ "$CXX" = "" ]; then
    CXX=c++
fi

cat << EOF > a.cc
#include <iostream>
void a() { std::cout << "a()" << std::endl; }
EOF

cat > b.cc << EOF
#include <iostream>
void a();
void b() { std::cout << "b()" << std::endl; a(); }
EOF

cat > c.cc << EOF
#include <iostream>
void b();
void c() { std::cout << "c()" << std::endl; b(); }
EOF

cat > d.cc << EOF
void c();
int main(int, char**) { c(); return 0; }
EOF

CXX_64="$CXX -arch x86_64"
CXX_32="$CXX -arch i386"

# Delete previous before rebuilding
if [ -e liba.dylib ]; then
    chmod 777 liba.dylib
    rm liba.dylib
fi
if [ -e libb.dylib ]; then
    chmod 777 libb.dylib
    rm libb.dylib
fi

$CXX_64 -o liba.dylib -dynamiclib a.cc
$CXX_32 -o liba32.dylib -dynamiclib a.cc
$CXX_64 -o a.o -c a.cc
ar rcs liba.a a.o
$CXX_64 -o libb.dylib -dynamiclib b.cc -L. -la
$CXX_64 -o libb.dylib -dynamiclib b.cc -L. -la
$CXX_64 -o libc.dylib -dynamiclib c.cc -L. -la -lb
$CXX_64 -o test-lib d.cc -L. -lc

# Make a dual-arch library
lipo -create liba.dylib liba32.dylb -output liba_both.dylib

# Change permissions in nasty way to test working with permissions
chmod 444 liba.dylib
chmod 400 libb.dylib
