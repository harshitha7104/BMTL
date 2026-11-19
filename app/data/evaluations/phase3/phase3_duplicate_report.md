# Duplicate and Near-Duplicate Candidates

- Duplicate/near-duplicate groups: 723
- Candidate pairs: `{"embedding_cosine_similarity": 677, "exact_sha256": 346, "phash_hamming_distance": 809}`
- Exact matches use SHA-256. Perceptual matches use pHash Hamming distance <= 4. Visual-similarity candidates use DINOv2 cosine >= 0.995.
- Similarity candidates are not proven duplicates. No files were deleted; groups must be held together for future splits.
