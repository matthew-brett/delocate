""" Second module

This one uses the external library
"""

cdef extern:
    int extfunc()

def func2():
    return 2


def func3():
    return extfunc()
