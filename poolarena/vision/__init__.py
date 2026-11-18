"""Camera-facing code. Everything here is optional: the rules engine, the
event detector and the overlay all run without OpenCV installed.
"""
from .source import FrameSource, ImageSource, KinectV2Source, VideoFileSource, WebcamSource, open_source

__all__ = ["FrameSource", "ImageSource", "KinectV2Source", "VideoFileSource",
           "WebcamSource", "open_source"]
