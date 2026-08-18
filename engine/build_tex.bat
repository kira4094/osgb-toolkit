@echo off
set VS=C:\Program Files\Microsoft Visual Studio\2022\Community
set MSVC=%VS%\VC\Tools\MSVC\14.38.33130
set INCLUDE=%MSVC%\include;%VS%\VC\Tools\MSVC\14.38.33130\include;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared
set LIB=%MSVC%\lib\x64;C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64;C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64
"%MSVC%\bin\Hostx64\x64\cl.exe" /nologo /EHsc /O2 /D_WIN32_WINNT=0x0601 /DNDEBUG ^
  /I "E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph\include" ^
  osgb_texture_dump.cpp ^
  /link "E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph\lib\osg.lib" ^
  "E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph\lib\osgDB.lib" ^
  "E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph\lib\osgUtil.lib" ^
  "E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph\lib\OpenThreads.lib" ^
  /out:osgb_texture_dump.exe
