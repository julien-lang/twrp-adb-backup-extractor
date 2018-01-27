I use TWRP 3.2.1-0 and ADB provided by Debian stable: 1:7.0.0+r33-1

I backup my phone:
  adb backup --twrp

I get a 7.1GB backup.ab

Then, I try to restore the backup
  adb restore backup.ab

TWRP show an error after few seconds:
  ... 
  

I wanted to read this 7GB backup file. When I could not find tools to do it for me, I got interested into the source code prototype:
	https://github.com/omnirom/android_bootable_recovery/blob/android-7.1/adbbu/twadbstream.h

I wrote a Python script to read that and to go though the backup.
But soon, I found out that the backup was not using the same structure

...
