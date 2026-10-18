from eval.matrix import function_dense as fd

SOURCE = '''class Cache:
    def get(self, key):
        return key

    async def put(self, key):
        return key


def helper(x):
    def get(y):
        return y
    return get(x)


async def fetch():
    return 1
'''


def test_units_follow_the_cornstack_rule():
    docs = fd.units("pkg/cache.py", SOURCE, pytest=False)
    assert sorted(docs) == ["pkg/cache.py/Cache/get", "pkg/cache.py/helper"]  # no async def, no nested get
    assert docs["pkg/cache.py/Cache/get"] == "pkg/cache.py/Cache/get\nclass Cache:\ndef get(self, key):\n        return key"
    assert docs["pkg/cache.py/helper"].startswith("pkg/cache.py/helper\ndef helper(x):\n")


def test_units_skip_test_paths_and_bad_files():
    assert fd.units("pkg/tests/cache.py", SOURCE, pytest=False) == {}
    assert fd.units("pkg/latest.py", SOURCE, pytest=False) == {}  # a substring match, as CoRNStack
    assert fd.units("testing/cache.py", SOURCE, pytest=True)  # pytest-dev repositories check the file name only
    assert fd.units("pkg/test_cache.py", SOURCE, pytest=True) == {}
    assert fd.units("pkg/cache.txt", SOURCE, pytest=False) == {}
    assert fd.units("pkg/old.py", "print 'x'\n", pytest=False) == {}


def test_files_and_accuracy():
    files = fd.files_of(["a.py/f", "b.py/C/g", "a.py/h", "c.py/k"])
    assert files == ["a.py", "b.py", "c.py"]
    assert fd.acc(files, ["b.py"], 1) is False
    assert fd.acc(files, ["b.py"], 5) is True
    assert fd.acc(files, ["a.py", "d.py"], 5) is False
