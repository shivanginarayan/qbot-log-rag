# Legacy Modules

This folder is for modules preserved from earlier experiments that are not part
of the active `milton_final_project` ROS 2 package.

Files placed here are kept in version control for reference, but they are not
installed by `setup.py`, do not provide `ros2 run` executables, and should not be
used by launch files unless they are intentionally restored.

To reactivate a module, move it back into `milton_final_project/`, add or restore
its `console_scripts` entry in `setup.py`, and verify the package builds.
