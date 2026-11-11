import pytest

from rundeps.models import Confidence
from rundeps.names import canonicalize, guessed_distribution, is_valid_package_name
from rundeps.resolver import Resolver, dedupe, load_import_map, merged_index


@pytest.fixture(scope="module")
def resolver() -> Resolver:
    return Resolver(index={})


@pytest.mark.parametrize(
    ("import_name", "package"),
    [
        ("PIL", "Pillow"),
        ("cv2", "opencv-python"),
        ("sklearn", "scikit-learn"),
        ("yaml", "PyYAML"),
        ("bs4", "beautifulsoup4"),
        ("dateutil", "python-dateutil"),
        ("skimage", "scikit-image"),
        ("dotenv", "python-dotenv"),
    ],
)
def test_known_mappings_resolve_with_high_confidence(resolver, import_name, package):
    resolution = resolver.resolve(import_name)

    assert resolution.package == package
    assert resolution.confidence is Confidence.HIGH
    assert resolution.installable and resolution.trusted


def test_mapping_file_is_not_empty():
    mapping = load_import_map()

    assert len(mapping) >= 40
    assert mapping["PIL"] == "Pillow"


def test_distribution_metadata_is_used(resolver):
    index = {"some_unknown_import": ["Some-Pkg"]}
    resolution = Resolver(index=index).resolve("some_unknown_import")

    assert resolution.package == "Some-Pkg"
    assert resolution.reason == "distribution metadata"


def test_distribution_metadata_prefers_exact_name():
    index = {"yaml": ["PyYAML", "yaml"]}
    resolution = Resolver(index=index, mapping={}).resolve("yaml")

    assert resolution.package == "yaml"


def test_dotted_mapping_key_beats_top_level():
    mapping = {"google": "google", "google.protobuf": "protobuf"}
    resolution = Resolver(index={}, mapping=mapping).resolve("google", "google.protobuf")

    assert resolution.package == "protobuf"


def test_same_name_import_is_medium_confidence(resolver):
    resolution = resolver.resolve("requests")

    assert resolution.package == "requests"
    assert resolution.confidence is Confidence.MEDIUM
    # Medium confidence is installable, but --yes alone must not approve it.
    assert resolution.installable
    assert not resolution.trusted


def test_unknown_import_is_low_confidence(resolver):
    resolution = resolver.resolve("something_weird")

    assert resolution.package == "something-weird"
    assert resolution.confidence is Confidence.LOW
    assert not resolution.installable


def test_local_mapping_override_wins():
    resolver = Resolver(index={}, mapping={"bs4": "my-internal-bs4"})

    assert resolver.resolve("bs4").package == "my-internal-bs4"


def test_dedupe_keeps_single_package():
    resolver = Resolver(index={}, mapping={"a": "Pillow", "PIL": "Pillow"})
    resolutions = [resolver.resolve("a"), resolver.resolve("PIL")]

    packages = [item.package for item in dedupe(resolutions)]

    assert packages == ["Pillow"]


def test_merged_index_combines_sources():
    merged = merged_index({"a": ["a1"]}, {"a": ["a2", "a1"], "b": ["b1"]})

    assert merged["a"] == ["a1", "a2"]
    assert merged["b"] == ["b1"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("PyYAML", "pyyaml"), ("python_dateutil", "python-dateutil"), ("Foo.Bar", "foo-bar")],
)
def test_canonicalize(raw, expected):
    assert canonicalize(raw) == expected


def test_guessed_distribution_normalizes_underscores():
    assert guessed_distribution("my_weird_module") == "my-weird-module"


@pytest.mark.parametrize(
    "name",
    ["requests", "opencv-python", "Pillow", "ruamel.yaml", "zope.interface"],
)
def test_valid_package_names(name):
    assert is_valid_package_name(name)


@pytest.mark.parametrize(
    "name",
    ["", "-e", "--index-url=http://evil", "some/pkg", "a b", "./local", "http://x/y", "_private"],
)
def test_rejected_package_names(name):
    assert not is_valid_package_name(name)
