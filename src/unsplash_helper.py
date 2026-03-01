#!/usr/bin/env python3
"""
unsplash_helper.py

Optional image source using the Unsplash API.
Use this as a fallback when Wikipedia returns no image.

Setup:
    1. Create a free account at https://unsplash.com/developers
    2. Create an app → copy the "Access Key"
    3. Set environment variable:  UNSPLASH_ACCESS_KEY=your_key_here
       OR pass it directly: get_unsplash_image("cat", access_key="your_key")

The free tier allows 50 requests/hour — plenty for a live lecture.

Usage (standalone test):
    python unsplash_helper.py "mitochondria"

Integration in transcription_reader.py:
    from unsplash_helper import get_unsplash_image

    # After wikipedia_best() returns no image:
    if not wiki.get("image_url"):
        fallback = get_unsplash_image(query)
        if fallback:
            wiki["image_url"] = fallback
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from typing import Optional


UNSPLASH_API_BASE = "https://api.unsplash.com"


def get_unsplash_image(
    query: str,
    access_key: Optional[str] = None,
    orientation: str = "landscape",   # landscape | portrait | squarish
    size: str = "regular",            # raw | full | regular | small | thumb
) -> Optional[str]:
    """
    Search Unsplash for a photo matching `query`.
    Returns the image URL string, or None on failure / no results.

    Args:
        query       : search term (e.g. "mitochondria", "cell division")
        access_key  : Unsplash Access Key. Falls back to UNSPLASH_ACCESS_KEY env var.
        orientation : preferred photo orientation
        size        : which size URL to return (regular ≈ 1080px wide)
    """
    key = access_key or os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not key:
        print(
            "[unsplash] No access key. Set UNSPLASH_ACCESS_KEY env var or pass access_key=.",
            file=sys.stderr,
        )
        return None

    params = urllib.parse.urlencode({
        "query": query,
        "per_page": 1,
        "orientation": orientation,
        "content_filter": "high",   # safe for educational use
    })
    url = f"{UNSPLASH_API_BASE}/search/photos?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Client-ID {key}",
                "Accept-Version": "v1",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        results = data.get("results", [])
        if not results:
            print(f"[unsplash] no results for '{query}'", file=sys.stderr)
            return None

        photo = results[0]
        image_url = photo.get("urls", {}).get(size)
        if image_url:
            print(f"[unsplash] ✓ found image for '{query}'", file=sys.stderr)
            # Unsplash attribution requirement — log it
            credit = photo.get("user", {}).get("name", "Unknown")
            print(f"[unsplash]   credit: Photo by {credit} on Unsplash", file=sys.stderr)
        return image_url

    except Exception as e:
        print(f"[unsplash] error for '{query}': {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "cell biology"
    print(f"Searching Unsplash for: '{query}'")
    url = get_unsplash_image(query)
    if url:
        print(f"Image URL: {url}")
    else:
        print("No image found.")
