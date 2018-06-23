
import gzip
import os
import re
import socket
import sys
import time

try:
    from dropbox import client, rest, session
except ImportError:
    print "Need Dropbox! (https://www.dropbox.com/developers/reference/sdk)"
    sys.exit(1)

try:
    from hurry.filesize import size
except ImportError:
    print "Need hurry.filesize! (http://pypi.python.org/pypi/hurry.filesize/)"
    sys.exit(1)

    
# - - - - - - - - - - CONFIGURATION OPTIONS! - - - - - - - - - - #

# MySQL login info:
MYSQL_DUMP_PATH = '/usr/bin/mysqldump'
MYSQL_ROOT_USER = 'root'
MYSQL_ROOT_PASS = 'my-root-passsword'
MYSQL_HOSTNAME  = 'localhost'
MYSQL_PORT      = 3306

# Dropbox (see documentation on how to do this):
DROPBOX_KEY     = 'dropbox-app-key'      # Dropbox API Key
DROPBOX_SECRET  = 'dropbox-app-secret'   # Dropbox API Secret
DROPBOX_ACCESS  = 'dropbox'              # Can be 'app_folder' or 'dropbox'
DROPBOX_FOLDER  = '/backups/mysql/'      # Folder to use in Dropbox - with trailing slash

# Other Options:
OPTION_GZIP      = True                  # gzip the resulting SQL file before uploading?
OPTION_USE_HOST  = True                  # Prepend the system hostname to the output filename?

# - - - - - - - - - - END OF CONFIG OPTIONS! - - - - - - - - - - #

# Dropbox token file - stores our oauth info for re-use:
DROPBOX_TOKEN_FILE = 'dropbox.token'

# Directory to work in (include trailing slash)
# Will be created if it doesn't exist.
TMP_DIR = os.getcwd() + '/tmp/'


def get_timestamp():
    """Returns a MySQL-style timestamp from the current time"""
    return time.strftime("%Y-%m-%d %H:%M:%S")

def do_mysql_backup(tmp_file):
    """Backs up the MySQL server (all DBs) to the specified file"""
    os.system("%s -u %s -p\"%s\" -h %s -P %d --opt --all-databases > %s" % (MYSQL_DUMP_PATH, MYSQL_ROOT_USER, MYSQL_ROOT_PASS, MYSQL_HOSTNAME, MYSQL_PORT, TMP_DIR + tmp_file))

def connect_to_dropbox():
    """Authorizes the app with Dropbox. Returns False if we can't connect"""

    # No I will not care about scope.
    global dropbox_client
    global dropbox_info

    access_token = ''

    # Do we have access tokens?
    while len(access_token) == 0:
        try:
            token_file = open(DROPBOX_TOKEN_FILE, 'r')
        except IOError:
            # Re-build the file and try again, maybe?
            get_new_dropbox_tokens()
            token_file = open(DROPBOX_TOKEN_FILE, 'r')
        
        access_token = token_file.read()        
        token_file.close()

    # Hopefully now we have token_key and token_secret...
    dropbox_client = client.DropboxClient(access_token)

    # Double-check that we've logged in
    try:
        dropbox_info = dropbox_client.account_info()
    except:
        # If we're at this point, someone probably deleted this app in their DB 
        # account, but didn't delete the tokens file. Clear everything and try again.
        os.unlink(DROPBOX_TOKEN_FILE)
        access_token = ''
        connect_to_dropbox()    # Who doesn't love a little recursion?


def get_new_dropbox_tokens():
    """Helps the user auth this app with Dropbox, and stores the tokens in a file"""

    flow = client.DropboxOAuth2FlowNoRedirect(DROPBOX_KEY, DROPBOX_SECRET)
    authorize_url = flow.start()

    print "Looks like you haven't allowed this app to access your Dropbox account yet!"
    print "1. Visit " + authorize_url
    print "2. Click \"Allow\" (you might have to log in first)"
    print "3. Copy the authorization code"

    code = raw_input("Enter authorization code here: ").strip()
    access_token, user_id = flow.finish(code)
    
    token_file = open(DROPBOX_TOKEN_FILE, 'w')
    token_file.write(access_token)
    token_file.close()


def main():
    # Make tmp dir if needed...
    if not os.path.exists(TMP_DIR):
        os.makedirs(TMP_DIR)

    # Are we prepending hostname to filename?
    hostname = (socket.gethostname() + '-') if(OPTION_USE_HOST == True) else ''

    MYSQL_TMP_FILE  = re.sub('[\\/:\*\?"<>\|\ ]', '-', hostname + 'backup-' + get_timestamp()) + '.sql'

    # Got final filename, continue on...
    print "Connecting to Dropbox..."
    connect_to_dropbox()

    print "Connected to Dropbox as " + dropbox_info['display_name']

    print "Creating MySQL backup, please wait..."
    do_mysql_backup(MYSQL_TMP_FILE)

    print "Backup done. File is " + size(os.path.getsize(TMP_DIR + MYSQL_TMP_FILE))

    if OPTION_GZIP == True:
        print "GZip enabled - compressing file..."

        # Write uncompressed file to gzip file:

        # Rant: Is chdir() really the only good way to get rid of dir structure in gz
        # files? GzipFile sounds like it would work, but....
        os.chdir(TMP_DIR)

        sql_file = open(TMP_DIR + MYSQL_TMP_FILE, 'rb')
        gz_file  = gzip.open(MYSQL_TMP_FILE + '.gz', 'wb')

        gz_file.writelines(sql_file)

        sql_file.close()
        gz_file.close()

        # Delete uncompressed TMP_FILE, set to .gz
        os.unlink(TMP_DIR + MYSQL_TMP_FILE)
        MYSQL_TMP_FILE = MYSQL_TMP_FILE + '.gz'

        # Tell the user how big the compressed file is:
        print "File compressed. New filesize: " + size(os.path.getsize(TMP_DIR + MYSQL_TMP_FILE))

    
    tmp_size = os.path.getsize(TMP_DIR + MYSQL_TMP_FILE)
    tmp_file = open(TMP_DIR + MYSQL_TMP_FILE, 'rb')

    print "Uploading backup to Dropbox..."
    uploader = dropbox_client.get_chunked_uploader(tmp_file, tmp_size)

    while uploader.offset < tmp_size:
        try:
            upload = uploader.upload_chunked(1024 * 1024)
        except rest.ErrorResponse, e:
            print "Error: %d %s" % (e.errno, e.strerror)
            pass

    uploader.finish(DROPBOX_FOLDER + MYSQL_TMP_FILE)
    tmp_file.close()

    print "File Uploaded as \"%s\" size: %d bytes" % (DROPBOX_FOLDER + MYSQL_TMP_FILE, tmp_size)
    
    print "Cleaning up..."
    os.unlink(TMP_DIR + MYSQL_TMP_FILE)


if __name__ == "__main__":
    main()
