set CXX=cl

(
echo #include ^<iostream^>
echo void a^(^) { std::cout ^<^< "a()" ^<^< std::endl^; }
) > a.cc

(
echo #include ^<iostream^>
echo void a^(^)^;
echo void b^(^) { std::cout ^<^< "b()" ^<^< std::endl^; }
) > b.cc

(
echo #include ^<iostream^>
echo void b^(^)^;
echo void c^(^) { std::cout ^<^< "c()" ^<^< std::endl^; }
) > c.cc

set CXX_64=%CXX% /arch:x64
set CXX_32=%CXX% /arch:x86

IF EXIST liba.DLL DEL /F test.DLL
IF EXIST libb.DLL DEL /F test.DLL

%CXX_64% a.cc /link /DLL /EXPORT:a /OUT:liba.DLL
%CXX_64% b.cc /link liba.lib /DLL /EXPORT:b /OUT:libb.DLL
%CXX_64% c.cc /link liba.lib libb.lib /EXPORT:c /DLL /OUT:libc.DLL

lib /OUT:a.lib a.obj
