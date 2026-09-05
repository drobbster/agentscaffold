def make_base():
    class Built:
        pass

    return Built


class Dynamic(make_base()):
    pass
