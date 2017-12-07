# Get Google Drive Streams
A simple tool that traverses a Google Drive, finds all files of mimeType containing 'video', and outputs .strm files that direct the Kodi GDrive Addon (https://forum.kodi.tv/showthread.php?tid=177557) to play them.

The script works from the Google drive Changes API method, so it remembers the last files it has processed, and subsequent executions only track changes from that point forward.

## Dependencies
To use the Python script directly
* Python 3.5+
* package *google-api-python-client*  
run `pip install --upgrade google-api-python-client` to install

## How-to
Download ([`getstreams.py`](https://raw.githubusercontent.com/cfbao/google-drive-trash-cleaner/v1.1.1rc/cleaner.py), place it in an empty local folder, and run it from command line.

By default, on first execution, `getstreams` starts from the inception of your Google Drive, finds all video files, prints their full path, then outputs a hierarchy of .strm files, each containing a link of the format `plugin://plugin.video.gdrive/?mode=video&filename=abc&title=xyz`.

### Google authorization
The first time you run `getstreams`, you will be prompted with a Google authorization page asking you for permission to view and manage your Google Drive files.
Once authorized, a credential file will be saved in `.credentials\get-google-drive-streams.json` under your home directory.
You don't need to manually authorize `getstreams` again until you delete this credential file or revoke permission on your Google [account](https://myaccount.google.com/permissions "Apps connected to your account") page.  
You can specify a custom location for the credential file by using the command line option `--credfile`. This is helpful if you're using multiple Google accounts with `getstreams`.

### `page_token` file
`getstreams` finds video files by scanning through your Google Drive activity history.
On first run, it must start from the very beginning to ensure no files are missed, so it might take some time.
After first run, `getstreams` saves a file named `page_token` in its own parent folder.
This file contains a single number indicating an appropriate starting position in your Google Drive activity history for future scans,
so they can be much faster than the first one. Each run of `getstreams` updates `page_token` as appropriate.  
You can specify a custom location or name for the `page_token` file by using the command line option `--ptokenfile`.

### More options
More command line options are available. You can read about them by running `getstreams --help`.
```
usage: getstreams.py [-h] [-v] [-q] [-t SECS] [-m] [--noprogress] [--nopath]
                     [--logfile PATH] [--ptokenfile PATH] [--streampath PATH]
                     [--credfile PATH]

optional arguments:
  -h, --help            show this help message and exit
  -v, --view            Only view which files are to be parsed without
                        creating files
  -q, --quiet           Quiet mode. Only show file count.
  -t SECS, --timeout SECS
                        Specify timeout period in seconds. Default is 300
  --noprogress          Don't show scanning progress. Useful when directing
                        output to files.
  --nopath              Do not parse full path for files, but store them flat.
                        Faster, but messy.
  --logfile PATH        Path to log file. Default is no logs
  --ptokenfile PATH     Path to page token file. Default is "page_token" in
                        getstreams.py's parent folder
  --streampath PATH     Path to stream output directory. Default is
                        strm/ in getstreams.py's parent folder.
  --credfile PATH       Path to OAuth2Credentials file. Default is
                        ~/.credentials/get-google-drive-streams.json
```

### Credit
All the heavy lifting here was stolen shamelessly from [Chenfeng Bao's Google Drive Trash Cleaner](https://github.com/cfbao/google-drive-trash-cleaner). The original idea for that script's working mechanism is borrowed from
[this Stack Overflow question](https://stackoverflow.com/questions/34803290/how-to-retrieve-a-recent-list-of-trashed-files-using-google-drive-api).
