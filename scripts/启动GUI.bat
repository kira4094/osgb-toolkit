@echo off
REM 启动 OSGB 网格简化工具 GUI
cd /d "%~dp0"
set "OSGROOT=E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph"
start "" pythonw osgb_gui.py
