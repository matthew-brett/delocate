#!/bin/bash
# Create libs used for testing
# Run in directory containing this file
# With thanks to https://dev.lsstcorp.org/trac/wiki/LinkingDarwin
# I ran this on a Snow Leopard machine with CXX=g++ ./make_libs.sh

if [ "$CXX" = "" ]; then
    CXX=clang++
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

$CXX -o liba.dylib -dynamiclib a.cc
$CXX -o a.o -c a.cc
ar rcs liba.a a.o
$CXX -o libb.dylib -dynamiclib b.cc -L. -la
$CXX -o libc.dylib -dynamiclib c.cc -L. -la -lb
$CXX -o test-lib d.cc -L. -lc
