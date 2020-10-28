pyinstaller --icon=mainicon.ico --noconsole main.py
md dist\main\images
copy images\*.* dist\main\images\
copy license.txt dist\main\
rename dist\main\main.exe colomusiccc.exe
rename dist\main\main.exe.manifest colomusiccc.exe.manifest