# This program is free software; you can redistribute it and/or modify it 
# under the terms of the GNU General Public License; either version 3 of 
# the License, or (at your option) any later version.
# You should have received a copy of the GNU General Public License 
# along with this program; if not, see <http://www.gnu.org/licenses>.

import httplib2
import os
import sys
import argparse
import time
import calendar
import logging
import warnings
import urllib

from apiclient import discovery
from apiclient.errors import HttpError
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage

if getattr(sys, 'frozen', False):
    # running in a bundle
    GETSTREAMS_PATH = sys.executable
else:
    # running as a normal Python script
    GETSTREAMS_PATH = os.path.realpath(__file__)
PAGE_TOKEN_FILE = os.path.join(os.path.dirname(GETSTREAMS_PATH), 'page_token')
CREDENTIAL_FILE = os.path.join(os.path.expanduser('~'), '.credentials', 'get-google-drive-streams.json')
STREAM_OUTPUT_PATH = os.path.join(os.path.dirname(GETSTREAMS_PATH), 'strm')

CLIENT_CREDENTIAL = {
    "client_id" : "201784684428-2ir8ukthflp7s2hhsdq96uuq8u0irlcv.apps.googleusercontent.com",
    "client_secret" : "dsj-XVI0myaCjjDHENfnSWff",
    "scope" : 'https://www.googleapis.com/auth/drive.readonly',
    "redirect_uri" : "urn:ietf:wg:oauth:2.0:oob",
    "token_uri" : "https://accounts.google.com/o/oauth2/token",
    "auth_uri" : "https://accounts.google.com/o/oauth2/auth",
    "revoke_uri" : "https://accounts.google.com/o/oauth2/revoke",
    "pkce" : True
}

PAGE_SIZE_LARGE = 1000
PAGE_SIZE_SMALL = 100
PAGE_SIZE_SWITCH_THRESHOLD = 3000
RETRY_NUM = 3
RETRY_INTERVAL = 2
TIMEOUT_DEFAULT = 300

class TimeoutError(Exception):
    pass

class PageTokenFile:
    def __init__(self, filePath):
        self.path = filePath
    
    def get(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                pageToken = int(f.read())
        except (FileNotFoundError, ValueError):
            pageToken = 0
        return pageToken
    
    def save(self, pageToken):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(str(pageToken))

def main():
    flags = parse_cmdline()
    logger = configure_logs(flags.logfile)
    pageTokenFile = PageTokenFile(flags.ptokenfile)
    for i in range(RETRY_NUM):
        try:
            service = build_service(flags)
            pageToken = pageTokenFile.get()
            mediaList, pageTokenBefore, pageTokenAfter = \
                get_media_list(service, pageToken, flags)
            pageTokenFile.save(pageTokenBefore)
            listEmpty = create_stream_files(service, mediaList, flags)
        except client.HttpAccessTokenRefreshError:
            print('Authentication error')
        except httplib2.ServerNotFoundError as e:
            print('Error:', e)
        except TimeoutError:
            print('Timeout: Google backend error.')
            print('Retries unsuccessful. Abort action.')
            return
        else:
            break
        time.sleep(RETRY_INTERVAL)
    else:
        print("Retries unsuccessful. Abort action.")
        return
    
    if listEmpty:
        pageTokenFile.save(pageTokenAfter)

def parse_cmdline():
    parser = argparse.ArgumentParser()
    # flags required by oauth2client.tools.run_flow(), hidden
    parser.add_argument('--auth_host_name', action='store', default='localhost', help=argparse.SUPPRESS)
    parser.add_argument('--noauth_local_webserver', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--auth_host_port', action='store', nargs='*', default=[8080, 8090], type=int, help=argparse.SUPPRESS)
    parser.add_argument('--logging_level', action='store', default='ERROR', 
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help=argparse.SUPPRESS)
    # flags defined by getstreams.py
    parser.add_argument('-v', '--view', action='store_true', 
            help='Only view which files are to be parsed without creating files')
    parser.add_argument('-q', '--quiet', action='store_true', 
            help='Quiet mode. Only show file count.')
    parser.add_argument('-t', '--timeout', action='store', type=int, default=TIMEOUT_DEFAULT, metavar='SECS',
            help='Specify timeout period in seconds. Default is %(default)s')
    parser.add_argument('--noprogress', action='store_true',
            help="Don't show scanning progress. Useful when directing output to files.")
    parser.add_argument('--nopath', action='store_true',
            help="Do not parse full path for files, but store them flat. Faster, but messy.")
    parser.add_argument('--logfile', action='store', metavar='PATH',
            help='Path to log file. Default is no logs')
    parser.add_argument('--ptokenfile', action='store', default=PAGE_TOKEN_FILE, metavar='PATH',
            help="Path to page token file. Default is \"{}\" in %(prog)s's parent folder".
                    format(os.path.basename(PAGE_TOKEN_FILE)))
    parser.add_argument('--streampath', action='store', default=STREAM_OUTPUT_PATH, metavar='PATH',
            help="Path to stream output directory. Default is %(default)s")
    parser.add_argument('--credfile', action='store', default=CREDENTIAL_FILE, metavar='PATH',
            help="Path to OAuth2Credentials file. Default is %(default)s")
    flags = parser.parse_args()
    if flags.timeout < 0:
        parser.error('argument --timeout must be nonnegative')
    if flags.logfile and flags.logfile.strip():
        flags.logfile = os.path.realpath(flags.logfile)
        os.makedirs(os.path.dirname(flags.logfile),    exist_ok=True)
    flags.ptokenfile = os.path.realpath(flags.ptokenfile)
    flags.credfile   = os.path.realpath(flags.credfile)
    flags.streampath = os.path.realpath(flags.streampath)
    os.makedirs(os.path.dirname(flags.ptokenfile),  exist_ok=True)
    os.makedirs(os.path.dirname(flags.credfile),    exist_ok=True)
    os.makedirs(os.path.realpath(flags.streampath), exist_ok=True)
    return flags

def configure_logs(logPath):
    logger = logging.getLogger('gdtc')
    logger.setLevel(logging.INFO)
    if not logPath:
        return logger
    logPath = logPath.strip('"')
    open(logPath, 'a').close()
    fileHandler = logging.FileHandler(
        logPath, mode='a', encoding='utf-8')
    logger.addHandler(fileHandler)
    return logger

def build_service(flags):
    credentials = get_credentials(flags)
    http = credentials.authorize(httplib2.Http())
    service = discovery.build('drive', 'v3', http=http)
    return service

def get_credentials(flags):
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    """
    store = Storage(flags.credfile)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.OAuth2WebServerFlow(**CLIENT_CREDENTIAL)
        credentials = tools.run_flow(flow, store, flags)
        print('credential file saved at\n\t' + flags.credfile)
    return credentials

def get_media_list(service, pageToken, flags, pathFinder=None):
    """Get list of video files and page token for future use.
    
    mediaList, pageTokenBefore, pageTokenAfter
        = get_media_list(service, pageToken, maxTrashDays, timeout)
    
    Iterate through Google Drive change list to find list of files of mimeType
    video. Return a list of files and a new page token for future use.
    
    service:        Google API service object
    pageToken:      An integer referencing a position in Drive change list.
                    Only changes made after this point will be checked. By 
                    assumption, files before this point are already scanned.
    mediaList:      List of media files to be made into streams.
                    Each file is represented as a dictionary with 
                    keys {'fileId', 'time', 'name'}.
    flags:          Flags parsed from command line. Should contain the 
                    following attributes:
                    --noprogress    don't show scanning progress
                    --quiet         don't show individual file info
                    --timeout       timeout in seconds
    pageTokenBefore:
                    An integer representing a point in Drive change list, 
                    >= 'pageToken'.
                    This page token is before everything in mediaList. Can 
                    be used as future pageToken no matter what.
    pageTokenAfter: An integer representing a point in Drive change list, 
                    >= 'pageToken'.
                    Can be used as future pageToken only if everything in 
                    mediaList is parsed.
    """
    response = execute_request(service.changes().getStartPageToken(), flags.timeout)
    latestPageToken = int(response.get('startPageToken'))
    currentTime = time.time()
    mediaList = []
    if not pageToken:
        pageToken = 1
    pageTokenBefore = pageToken
    pageSize = PAGE_SIZE_LARGE
    progress = ScanProgress(quiet=flags.quiet, noProgress=flags.noprogress)
    if not pathFinder and not flags.nopath:
        pathFinder = PathFinder(service)
    while pageToken:
        if latestPageToken - int(pageToken) < PAGE_SIZE_SWITCH_THRESHOLD:
            pageSize = PAGE_SIZE_SMALL
        request = service.changes().list(
                    pageToken=pageToken, includeRemoved=False,
                    pageSize=pageSize,
                    fields='nextPageToken,newStartPageToken,'
                    'changes(fileId,time,file(name,parents,mimeType))'
                    )
        response = execute_request(request, flags.timeout)
        items = response.get('changes', [])
        for item in items:
            progress.print_time(item['time'])
            if 'video' in item['file']['mimeType']:
                if not flags.nopath:
                    disp = pathFinder.get_path(item['fileId'], fileRes=item['file'])
                else:
                    disp = item['file']['name']
                progress.found(item['time'], disp)
                mediaList.append({'fileId': item['fileId'], 'time': item['time'],
                                        'fullpath': disp, 'name': item['file']['name']})
        pageToken = response.get('nextPageToken')
        if not mediaList:
            pageTokenBefore = pageToken
    progress.clear_line()
    return mediaList, pageTokenBefore, int(response.get('newStartPageToken'))

def create_stream_files(service, mediaList, flags):
    """Create stream files from items in mediaList
    
    listEmpty = create_stream_files(service, mediaList, flags)
    
    service:        Google API service object
    mediaList:      List of files to be parsed. Each file is represented as
                    a dictionary with keys {'fileId', 'time', 'name'}.
    flags:          Flags parsed from command line arguments.
    listEmpty:      Return True if mediaList is either empty on input or 
                    emptied by this function, False otherwise.
    """
    logger = logging.getLogger('gdtc')
    n = len(mediaList)
    if n == 0:
        print('No stream files to be created')
        return True
    if flags.view:
        if n == 1:
            print('{:} stream to be created'.format(n))
        else:
            print('{:} streams to be created'.format(n))
        return False
    print('Creating Streams...')
    for item in reversed(mediaList):
        strmfile = os.path.join(flags.streampath,item['fullpath'] + '.strm')
        os.makedirs(os.path.dirname(strmfile), exist_ok=True)
        with open(strmfile, 'w', encoding='utf-8') as f:
            gdriveurl = "plugin://plugin.video.gdrive/?mode=video&filename=" + \
                                        urllib.parse.quote_plus(item['fileId']) + "&title=" \
                                        + urllib.parse.quote_plus(item['name'])
            f.write(str(gdriveurl))
        logger.info(item['time'] + ''.ljust(4) + item['name'])
    print('Files successfully written')
    return True

class ScanProgress:
    def __init__(self, quiet, noProgress):
        self.printed = "0000-00-00"
        self.noItemYet = True
        self.quiet = quiet
        self.noProgress = noProgress
    
    def print_time(self, timeStr):
        """print yyyy-mm-dd only if not yet printed"""
        if self.noProgress:
            return
        ymd = timeStr[:10]
        if ymd > self.printed:
            print('\rScanning files from ' + ymd, end='')
            self.printed = ymd
    
    def found(self, time, name):
        """found an item, print its info"""
        if self.quiet:
            return
        if not self.noProgress:
            print('\r' + ''.ljust(40) + '\r', end='')
        if self.noItemYet:
            print('Date added'.ljust(24) + ''.ljust(4) + 'File Name/Path')
            self.noItemYet = False
        print(time + ''.ljust(4) + name)
        if not self.noProgress:
            print('\rScanning files from ' + self.printed, end='')
    
    def clear_line(self):
        print('\r' + ''.ljust(40) + '\r', end='')
        print()

class PathFinder:
    def __init__(self, service, cache=None):
        self.service = service
    # each item in self.cache is a list with 2 elements
    # self.cache[id][0] is the full path of id
    # self.cache[id][1] is the number of times id has been queried
        if cache:
            self.cache = cache
        else:
            self.cache = dict()
    # self.expanded contains all ids that have all their children cached
        self.expanded = set()
    
    def get_path(self, id, fileRes=None):
        """Find the full path for id
        
        fileRes:    File resource for id. 
                    Must have 'name' and 'parents' attributes if available.
                    If None or unspecified, an API call is made to query"""
        if id in self.cache:
            if self.cache[id][1]>1 and id not in self.expanded:
                # find and cache all children if id is requested more than once
                self.expand_cache(id)
            self.cache[id][1] += 1
            return self.cache[id][0]
        if not fileRes:
            request = self.service.files().get(fileId=id, fields='name,parents')
            fileRes = execute_request(request)
        try:
            parentId = fileRes['parents'][0]
            self.cache[id] = [self.get_path(parentId) + os.sep + fileRes['name'], 1]
        except KeyError:
            self.cache[id] = [fileRes['name'], 1]
        return self.cache[id][0]
    
    def expand_cache(self, id):
        if id in self.expanded:
            return
        npt = None
        while True:
            request = self.service.files().list(
                    q="'{:}' in parents".format(id), 
                    pageToken=npt, 
                    fields="files(id,name),nextPageToken",
                    pageSize=1000)
            response = execute_request(request)
            for file in response['files']:
                if file['id'] in self.cache:
                    continue
                self.cache[file['id']] = [self.cache[id][0] + os.sep + file['name'], 0]
            try:
                npt = response['nextPageToken']
            except KeyError:
                break
        self.expanded.add(id)
    
    def clear():
        self.cache.clear()

def execute_request(request, timeout=TIMEOUT_DEFAULT):
    """Execute Google API request
    Automatic retry upon Google backend error (500) until timeout
    """
    while timeout >= 0:
        try:
            response = request.execute()
        except HttpError as e:
            if int(e.args[0]['status']) == 500:
                timeout -= RETRY_INTERVAL
                time.sleep(RETRY_INTERVAL)
                continue
            raise e
        else:
            return response
    raise TimeoutError

def parse_time(rfc3339):
    """parse the RfC 3339 time given by Google into Unix time"""
    time_str = rfc3339.split('.')[0]
    return calendar.timegm(time.strptime(time_str, '%Y-%m-%dT%H:%M:%S'))

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped by user')
