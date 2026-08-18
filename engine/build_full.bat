@echo off
setlocal
set "VS=C:\Program Files\Microsoft Visual Studio\2022\Community"
set "MSVC=%VS%\VC\Tools\MSVC\14.38.33130"
set "SDK=C:\Program Files (x86)\Windows Kits\10"
set "SDKVER=10.0.26100.0"
set "PROJ=E:\Resource\StadiumZG\osgb-toolkit"
set "OSGROOT=%PROJ%\thirdparty\OpenSceneGraph"
set "OSGINC=%OSGROOT%\include"
set "OSGLIB=%OSGROOT%\lib"
set "ENGINEDIR=%PROJ%\engine"
set "CL_EXE=%MSVC%\bin\Hostx64\x64\cl.exe"
set "INCLUDE=%MSVC%\include;%SDK%\Include\%SDKVER%\ucrt;%SDK%\Include\%SDKVER%\um;%SDK%\Include\%SDKVER%\shared;%OSGINC%"
set "LIB=%MSVC%\lib\x64;%SDK%\Lib\%SDKVER%\ucrt\x64;%SDK%\Lib\%SDKVER%\um\x64;%OSGLIB%"

"%CL_EXE%" /nologo /EHsc /O2 /std:c++20 /D NOMINMAX /D WIN32_LEAN_AND_MEAN /D NDEBUG /utf-8 ^
  /I "%OSGINC%" /I "%ENGINEDIR%" ^
  "%ENGINEDIR%\osgb_full.cpp" ^
  /link /LIBPATH:"%OSGLIB%" osg.lib osgDB.lib osgUtil.lib OpenThreads.lib ^
  /OUT:"%ENGINEDIR%\osgb_full.exe"
echo EXITCODE=%ERRORLEVEL%
endlocal
