@echo off
REM 启动 OSGB 双段 GUI(无控制台窗口)
cd /d "%~dp0"
set "OSGROOT=E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph"
start "" pythonw osgb_gui_a.py
