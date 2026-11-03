@echo off
setlocal
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1
cd /d "%~dp0.."
if not exist build\native mkdir build\native
cl /nologo /O2 /EHsc /std:c++14 /LD hardware\hls\lesion_accel.cpp /Fobuild\native\lesion_accel.obj /link /OUT:build\native\lesion.dll /IMPLIB:build\native\lesion_accel.lib /EXPORT:lesion_accel
exit /b %errorlevel%
