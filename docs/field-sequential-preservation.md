# Preserving field-sequential stereo: pixels, eye order and time

The [display guide](../readme.md#can-field-sequential-3d-be-saved) describes converting alternating eye fields into progressive stereo pairs.
Repacking can preserve the field images; it cannot establish when the cameras exposed them or synchronize captures that happened at different times.
These are separate questions, and a test of one does not prove the other.

## Field order and eye order are independent

FFmpeg's [`separatefields`](https://ffmpeg.org/ffmpeg-filters.html#separatefields) emits two half-height images per input frame, in the order indicated by the input's field dominance.
Top-field-first (`tff`) means the top rows come first; bottom-field-first (`bff`) means the bottom rows come first.
Neither flag says which eye those rows represent.

[`stereo3d`](https://ffmpeg.org/ffmpeg-filters.html#stereo3d) with input `al` assigns the first image to the left eye and the second to the right; `ar` reverses those assignments.
The four valid combinations are:

| Field dominance | First eye | Left-eye rows | Right-eye rows | Input to `stereo3d` |
|---|---|---|---|---|
| TFF | Left | Top | Bottom | `al` |
| TFF | Right | Bottom | Top | `ar` |
| BFF | Left | Bottom | Top | `al` |
| BFF | Right | Top | Bottom | `ar` |

When dominance is absent or wrong, `setfield=tff` or `setfield=bff` declares it before splitting.
It does not discover field order, identify the eyes, change the pixels, or synchronize the source.
Establish both orders from the source's documentation or identifiable content before choosing the conversion.

## Packing preserves samples, not necessarily simultaneous exposures

Consider two possible sources:

- **Synchronized capture, sequential storage:** left and right cameras expose together, then their images are stored in alternating fields. Pairing the fields retains that synchronized pair.
- **Staggered capture:** the eyes are sampled at successive field times. Pairing the fields retains their time difference; no motion compensation occurs in this filter chain.

For a source sampled once per field, the difference between adjacent eye samples is one field period:

| Fields per second | Stereo pairs per second | Adjacent sample separation |
|---|---|---|
| 50 | 25 | 20 ms |
| 60000/1001 | 30000/1001 | 1001/60 ms, approximately 16.683 ms |
| 60 | 30 | approximately 16.667 ms |

Those intervals apply when the eyes were sampled successively, not to every recording with sequential storage.
Presentation timestamps alone do not establish camera exposure times.

Motion matters: if the test object's right-eye position is six pixels to the right of its left-eye position at the same capture time, and it moves two pixels per field, a later right-eye exposure yields an eight-pixel difference.
A later left-eye exposure yields four pixels instead.
The converter preserves those images; it does not recover the missing simultaneous views.

## Full SBS does not require another loss of horizontal samples

For an input raster of width W and height 2H, each separated field is W by H.
The filters below only rearrange those samples:

```text
separatefields,stereo3d=al:sbsl   -> 2W by H, left eye on the left
separatefields,stereo3d=al:abl    -> W by 2H, left eye on top
```

Use `ar` instead when the right eye comes first.
Both outputs retain W by H stored samples per eye; scaling to a chosen TV raster is a later operation with its own resolution and aspect-ratio consequences.
These intermediate layouts do not by themselves declare a physical display mode or guarantee automatic switching into 3D.

The FFmpeg 7.1 implementations of [field extraction](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1/libavfilter/vf_separatefields.c) and [stereo pairing](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1/libavfilter/vf_stereo3d.c) provide the source cross-check: extraction steps through alternate rows, while pairing consumes consecutive images and sets the output geometry and cadence.

## Reproduce the verification

From the repository root, with Python 3 and FFmpeg installed:

```sh
python3 .github/scripts/verify_fieldseq.py
```

Use `--ffmpeg /path/to/ffmpeg` when the executable is not on PATH.
The [test](../.github/scripts/verify_fieldseq.py) constructs the woven RGB24 fields directly in Python, independently of FFmpeg's `framepack` and `weave` filters.
Each field has an eye identifier, capture-sample identifier, row/column pattern and moving target.
It then runs the documented conversion and checks:

- Every output byte, including the last pair, across 32 combinations: 25 and 30000/1001 input frames per second, both field orders, both first-eye orders, full SBS and top-bottom, synchronized and staggered capture.
- Exact output timestamps and pair count, using FFmpeg's `showinfo` time base rather than rounded decimal timestamps.
- The motion-dependent four/eight-pixel differences in staggered capture, versus six pixels in synchronized capture.
- Negative controls: a wrong field declaration or a wrong first-eye declaration swaps the views and fails the correct-eye oracle.

Verified locally with FFmpeg 7.1 on Windows: all three test groups passed, exercising 42 conversions.
The accompanying CI runs the same test with the Ubuntu-packaged FFmpeg and prints the actual version in its log.
This verifies sample packing, eye assignment and cadence on synthetic lossless RGB data.
It does not validate a particular recording's exposure timing, subsampled chroma, a decoder's stereo metadata, or physical display behaviour.
