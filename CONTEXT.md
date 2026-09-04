# SegDete

SegDete monitors paved surfaces by turning camera captures into classified and annotated inspection results.

## Language

**Camera replay**:
A test acquisition mode in which the inspection service treats recorded field images as camera captures.
_Avoid_: Offline test, serial camera, replay processor

**Inspection service**:
The single owner of capture processing and result publication, regardless of whether a capture is physical or replayed.
_Avoid_: Replay script, uploader
