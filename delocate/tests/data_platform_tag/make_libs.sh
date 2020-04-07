#!/bin/bash
# Create libs used for testing
# Run in directory containing this file
# With thanks to https://dev.lsstcorp.org/trac/wiki/LinkingDarwin
# I ran this on a Snow Leopard machine with CXX=g++ ./make_libs.sh

if [ "$CXX" = "" ]; then
    CXX=c++
fi

cat << EOF > a.cc
#include <stdio.h>
void a() { printf("a()\n"); }
EOF

cat > b.cc << EOF
#include <stdio.h>
void a();
void b() { printf("b()\n"); a(); }
EOF

cat > c.cc << EOF
#include <stdio.h>
void b();
void c() {printf("c()\n"); b(); }
EOF

cat > d.cc << EOF
void c();
int main(int, char**) { c(); return 0; }
EOF

CXX_64="$CXX -arch x86_64"
CXX_32="$CXX -arch i386"

rm ./*.dylib

# 10.6 section

$CXX_64 -o liba.6.dylib -mmacosx-version-min=10.6 -dynamiclib a.cc
$CXX_64 -o libb.6.dylib -mmacosx-version-min=10.6 -dynamiclib b.cc -L. -la.6
$CXX_64 -o libc.6.dylib -mmacosx-version-min=10.6 -dynamiclib c.cc -L. -la.6 -lb.6

# 10.9 section
$CXX_64 -o liba.9.dylib -mmacosx-version-min=10.9 -dynamiclib a.cc
$CXX_64 -o libb.9.dylib -mmacosx-version-min=10.9 -dynamiclib b.cc -L. -la.9
$CXX_64 -o libc.9.dylib -mmacosx-version-min=10.9 -dynamiclib c.cc -L. -la.9 -lb.9

# 10.9 base on 10.6
$CXX_64 -o libc.9.1.dylib -mmacosx-version-min=10.9 -dynamiclib c.cc -L. -la.6 -lb.6

# 10.14 section
$CXX_64 -o liba.14.dylib -mmacosx-version-min=10.14 -dynamiclib a.cc
$CXX_64 -o libb.14.dylib -mmacosx-version-min=10.14 -dynamiclib b.cc -L. -la.14
$CXX_64 -o libc.14.dylib -mmacosx-version-min=10.14 -dynamiclib c.cc -L. -la.14 -lb.14

$CXX_64 -o liba.dylib -dynamiclib a.cc
$CXX_32 -o liba32.6.dylib -mmacosx-version-min=10.6 -dynamiclib a.cc
$CXX_32 -o liba32.9.dylib -mmacosx-version-min=10.9 -dynamiclib a.cc
$CXX_32 -o liba32.14.dylib -mmacosx-version-min=10.14 -dynamiclib a.cc

$CXX_64 -o a.o -c a.cc
ar rcs liba.a a.o
$CXX_64 -o libb.dylib -dynamiclib b.cc -L. -la
$CXX_64 -o libc.dylib -dynamiclib c.cc -L. -la -lb
$CXX_64 -o test-lib d.cc -L. -lc

# Make a dual-arch library
lipo -create liba.9.dylib liba32.14.dylib -output liba_both.dylib

$CXX_64 -o liba.6.so -mmacosx-version-min=10.6 -bundle a.cc
$CXX_64 -o liba.9.so -mmacosx-version-min=10.9 -bundle a.cc
$CXX_64 -o liba.14.so -mmacosx-version-min=10.14 -bundle a.cc