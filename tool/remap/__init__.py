"""Matreshka Remap, as a page of the viewer's window.

The application from E:\\05_Render\\Matreshka_Remap (its commit 458a439 and
the working tree of 2026-10-15), copied as it is: the same window, the same
tables, the same renderer. What changed to make it live here:

  * its imports are relative, because three of its module names (main,
    logfile, depends) are the viewer's too;
  * it keeps remap_tool.json, ToRemap and OUT beside the viewer
    (`constants.app_dir` is the viewer's) and finds its tables, icons and
    Check.png in this folder;
  * its log is the viewer's log (`logfile.py` here only hands lines on);
  * its dark palette and style sheet are set on its own window, not on the
    whole application -- see `page.make`.

The Blender baking scripts stayed in the remap project: they run in Blender.
"""
