# -*- coding: utf-8 -*-
#
#  files
#  *****
#
# Backend supports for jQuery File Uploader, and implementation of the
# classes executed when an HTTP client contact /files/* URI

from __future__ import with_statement
import time
import copy

from twisted.internet import fdesc
from twisted.internet.defer import inlineCallbacks
from cyclone.web import os

from globaleaks.settings import transact
from globaleaks.handlers.base import BaseHandler
from globaleaks.handlers.authentication import authenticated
from globaleaks import utils
from globaleaks.utils import log
from globaleaks import settings
from globaleaks.rest import errors
from globaleaks import models

__all__ = ['Download', 'FileInstance']


SUBMISSION_DIR = os.path.join(settings.gldata_path, 'submission')
if not os.path.isdir(SUBMISSION_DIR):
    os.mkdir(SUBMISSION_DIR)


def serialize_file(internalfile):

    file_desc = {
        'size' : internalfile.size,
        'content_type' : internalfile.content_type,
        'name' : internalfile.name,
        'creation_date': utils.prettyDateTime(internalfile.creation_date),
        'id' : internalfile.id,
    }

    return file_desc

@transact
def register_files_db(store, files, relationship, internaltip_id):

    files_list = []
    for single_file in files:
        original_fname = single_file['filename']
        file_request = { 'name' : original_fname,
                         'content_type' : single_file.get('content_type'),
                         'mark' : unicode(models.InternalFile._marker[0]),
                         'size' : len(single_file['body']),
                         'internaltip_id' : unicode(internaltip_id),
                         'sha2sum' : '',
                         'file_path': relationship[original_fname]
                       }

        new_file = models.InternalFile(file_request)
        store.add(new_file)
        files_list.append(serialize_file(new_file))

    return files_list

def dump_files_fs(files):
    """
    @param files: files uploaded in Cyclone upload
    @return: a relationship dict linking the filename with the random
        filename saved in the disk
    """
    files_saved = {}
    for single_file in files:
        saved_name = utils.random_string(26, 'A-Z,a-z,0-9')
        filelocation = os.path.join(SUBMISSION_DIR, saved_name)

        with open(filelocation, 'w+') as fd:
            fdesc.setNonBlocking(fd.fileno())
            fdesc.writeToFD(fd.fileno(), single_file['body'])

        files_saved.update({single_file['filename']: saved_name })

    return files_saved


@transact
def get_tip_by_receipe(store, receipt):
    """
    Tip need to be Whistleblower authenticated
    """
    wbtip = store.find(models.WhistleblowerTip,
                       models.WhistleblowerTip.receipt == unicode(receipt)).one()
    if not wbtip:
        raise errors.ReceiptGusNotFound
    else:
        return wbtip.id

@transact
def get_tip_by_internaltip(store, id):
    itip = store.find(models.InternalTip,
                      models.InternalTip.id == unicode(id)).one()
    if not itip:
        raise errors.SubmissionGusNotFound
    elif itip.mark != models.InternalTip._marker[0]:
        raise errors.SubmissionConcluded
    else:
        return itip.id



# This is different from FileInstance, just because there are a different authentication requirements
class FileAdd(BaseHandler):
    """
    T4
    WhistleBlower interface for upload a new file
    """
    @inlineCallbacks
    @authenticated('wb')
    def post(self, tip_id, *args):
        """
        Parameter: submission_gus
        Request: Unknown
        Response: Unknown
        Errors: SubmissionGusNotFound, SubmissionConcluded
        """
        result_list = []

        itip_id = yield get_tip_by_internaltip(self.current_user['password'])

        # measure the operation of all the files (via browser can be selected
        # more than 1), because all files are delivered in the same time.
        start_time = time.time()

        file_array, files = self.request.files.popitem()

        # First iterloop, dumps the files in the filesystem,
        # and exception raised here would prevent the InternalFile recordings
        try:
            relationship = dump_files_fs(files)
        except OSError, e:
            # TODO danger error log: unable to save in FS
            raise errors.InternalServerError

        # Second iterloop, create the objects in the database
        file_list = yield register_files_db(files, relationship, itip_id)

        for file_desc in file_list:
            file_desc['elapsed_time'] = time.time() - start_time
            result_list.append(file_desc)

        self.set_status(201) # Created
        self.write(result_list)


class FileInstance(BaseHandler):
    """
    U4
    This is the Storm interface to supports JQueryFileUploader stream
    """

    @inlineCallbacks
    def post(self, submission_id, *args):
        """
        Parameter: submission_gus
        Request: Unknown
        Response: Unknown
        Errors: SubmissionGusNotFound, SubmissionConcluded
        """
        result_list = []

        itip_id = yield get_tip_by_internaltip(submission_id)

        # measure the operation of all the files (via browser can be selected
        # more than 1), because all files are delivered in the same time.
        start_time = time.time()

        file_array, files = self.request.files.popitem()

        # First iterloop, dumps the files in the filesystem,
        # and exception raised here would prevent the InternalFile recordings
        try:
            relationship = dump_files_fs(files)
        except OSError, e:
            # TODO danger error log: unable to save in FS
            raise errors.InternalServerError

        # Second iterloop, create the objects in the database
        file_list = yield register_files_db(files, relationship, itip_id)

        for file_desc in file_list:
            file_desc['elapsed_time'] = time.time() - start_time
            result_list.append(file_desc)

        self.set_status(201) # Created
        self.write(result_list)


class Download(BaseHandler):

    """
    @inlineCallbacks
    def get(self, tip_gus, CYCLON_DIRT, file_gus, *uriargs):

        # tip_gus needed to authorized the download
        print tip_gus, file_gus

        answer = yield FileOperations().get_file_access(tip_gus, file_gus)

        # verify if receiver can, in fact, download the file, otherwise
        # raise DownloadLimitExceeded

        fileContent = answer['data']
        # keys:  'content'  'sha2sum'  'size' : 'content_type' 'file_name'

        self.set_status(answer['code'])

        self.set_header('Content-Type', fileContent['content_type'])
        self.set_header('Content-Length', fileContent['size'])
        self.set_header('Etag', '"%s"' % fileContent['sha2sum'])

        filelocation = os.path.join(settings.config.advanced.submissions_dir, file_gus)

        chunk_size = 8192
        filedata = ''
        with open(filelocation, "rb") as requestf:
            fdesc.setNonBlocking(requestf.fileno())
            while True:
                chunk = requestf.read(chunk_size)
                filedata += chunk
                if len(chunk) == 0:
                    break

        self.write(filedata)
        self.finish()
    """