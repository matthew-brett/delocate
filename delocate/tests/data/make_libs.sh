#!/bin/bash
# Create libs used for testing
# Run in directory containing this file
# With thanks to https://dev.lsstcorp.org/trac/wiki/LinkingDarwin

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

clang++ -o liba.dylib -dynamiclib a.cc
clang++ -o libb.dylib -dynamiclib b.cc -L. -la
clang++ -o libc.dylib -dynamiclib c.cc -L. -la -lb
clang++ -o test-lib d.cc -L. -lc
