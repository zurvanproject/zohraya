# Nasuraya Visual Genome | external QA gate

Version 1.1 is a limited external gate against falsely accepting unreviewed
images. It requires **real decoded image files**, a hash-locked reference and a
review tied to candidate/reference SHA256. It does NOT automatically count toes,
compare face embeddings, inpaint pixels, change ChatGPT image model weights or
prove that a generator used the image as conditioning.

Run offline:

    python -m pip install 'Pillow>=11,<13'
    python -m unittest discover -s visual_genome/tests -v

API:

    from visual_genome.gate import image_info, inspect_candidate
    r = inspect_candidate(reference_path, approved_sha256, candidate_path, manual_review)

The reference photograph itself is **not committed**. Approval of a canonical
image must be an explicit owner action; never substitute a newly generated
image or fictional prompt for an actual approved reference.

Interpretation: PASS = only a fully attested manual review of visible features;
FAIL = a detected mismatch or reference-integrity failure; UNVERIFIED = missing,
hidden, cropped or unreviewed evidence. Even PASS cannot prove generator
provenance. The next optional subsystem is a pixel-backed vision detector with
calibrated accuracy on digitigrade three-toed feet.

The complete expanded experimental prototype (with ROI review preview,
genome initialization CLI and 30 local tests) can be maintained as a
separate deliverable for owner review, not silently merged into main.
