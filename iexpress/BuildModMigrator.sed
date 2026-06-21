[Version]
Class=IEXPRESS
SEDVersion=3

[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles

[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
; The .exe that IExpress will produce:
TargetName=BuildModMigrator.exe
FriendlyName=Build Mod Migrator
; IExpress can't launch a .bat directly (it errors with
; "Error creating process Command.com /c ..."), so we invoke it
; explicitly through cmd.exe instead:
AppLaunched=cmd /c build_windows.bat
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0="build_windows.bat"
FILE1="mod_migrator_gui.py"

[SourceFiles]
SourceFiles0=.

[SourceFiles0]
%FILE0%=
%FILE1%=
