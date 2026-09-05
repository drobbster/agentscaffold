from typing import Generic, TypeVar

T = TypeVar("T")


class Bar:
    pass


class Foo(Generic[T], Bar):
    pass
