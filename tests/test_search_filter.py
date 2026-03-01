import unittest

from app.retrieval.search import build_metadata_filter


class SearchFilterTests(unittest.TestCase):
    def test_build_metadata_filter_none(self) -> None:
        self.assertIsNone(build_metadata_filter(platform=None, product=None))

    def test_build_metadata_filter_single(self) -> None:
        self.assertEqual(
            build_metadata_filter(platform="android", product=""),
            {"$and": [{"platform": {"$eq": "android"}}]},
        )

    def test_build_metadata_filter_both(self) -> None:
        self.assertEqual(
            build_metadata_filter(platform="android", product="video-calling"),
            {
                "$and": [
                    {"platform": {"$eq": "android"}},
                    {"product": {"$eq": "video-calling"}},
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
