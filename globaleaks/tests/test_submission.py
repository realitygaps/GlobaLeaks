from __future__ import unicode_literals
import re

from twisted.internet.defer import inlineCallbacks

# ovverride GLsetting
from globaleaks.settings import GLSetting, transact
from globaleaks.tests import helpers

from globaleaks import models

from globaleaks.jobs import delivery_sched
from globaleaks.handlers import files, authentication, submission, tip
from globaleaks.handlers.admin import update_context, create_receiver, get_receiver_list
from globaleaks.rest import errors

from Crypto.Hash import SHA256

class TestSubmission(helpers.TestGL):
    filename = ''.join(unichr(x) for x in range(0x400, 0x4FF))
    body = ''.join(unichr(x) for x in range(0x370, 0x3FF))
    dummyFiles = []
    dummyFiles.append({
        'body': body[0:GLSetting.generic_limit].encode('utf-8'),
        'content_type': 'application/octect',
        'filename': 'aaaaaa'
    })

    dummyFiles.append({
        'body': 'aaaaaa',
        'content_type': 'application/octect',
        'filename': filename[0:GLSetting.name_limit]
    })

    # --------------------------------------------------------- #
    @inlineCallbacks
    def test_create_submission(self):
        submission_desc = self.dummySubmission
        submission_desc['finalize'] = True
        del submission_desc['submission_gus']

        status = yield submission.create_submission(submission_desc, finalize=True)
        receipt = yield submission.create_whistleblower_tip(status)

        retval = re.match(GLSetting.receipt_regexp, receipt)
        self.assertTrue(retval)

    @inlineCallbacks
    def emulate_files_upload(self, associated_submission_id):
        relationship = files.dump_files_fs(self.dummyFiles)
        self.file_list = yield files.register_files_db(self.dummyFiles,
                relationship, associated_submission_id)
        self.assertEqual(len(self.file_list), 2)

        file_list = yield files.register_files_db(
            self.dummyFiles, relationship, associated_submission_id,
        )
        self.assertEqual(len(file_list), 2)


    @inlineCallbacks
    def test_create_internalfiles(self):
        yield self.emulate_files_upload(self.dummySubmission['submission_gus'])
        # fill self.file_list
        for file_desc in self.file_list:
            keydiff = set(['size', 'content_type', 'name', 'creation_date', 'id']) - set(file_desc.keys())
            self.assertFalse(keydiff)


    @transact
    def _force_finalize(self, store, submission_id):
        it = store.find(models.InternalTip, models.InternalTip.id == submission_id).one()
        it.mark = models.InternalTip._marker[1] # 'finalized'

    @inlineCallbacks
    def test_create_receiverfiles(self):
        # test made to approach a strange behaviour...
        yield self.emulate_files_upload(self.dummySubmission['submission_gus'])
        yield self._force_finalize(self.dummySubmission['submission_gus'])

        filesdict = yield delivery_sched.file_preprocess()

        processdict = delivery_sched.file_process(filesdict)
        # return a dict { "file_uuid" : checksum }

        ret = yield delivery_sched.receiver_file_align(filesdict, processdict)
        self.assertEqual(len(ret), 4)


    @inlineCallbacks
    def test_access_from_receipt(self):
        submission_desc = self.dummySubmission
        submission_desc['finalize'] = True
        del submission_desc['submission_gus']

        status = yield submission.create_submission(submission_desc, finalize=True)
        receipt = yield submission.create_whistleblower_tip(status)

        wb_access_id = yield authentication.login_wb(receipt)

        # remind: return a tuple (serzialized_itip, wb_itip)
        wb_tip = yield tip.get_internaltip_wb(wb_access_id)

        # In the WB/Receiver Tip interface, wb_fields are called fields.
        # This can be uniformed when API would be cleaned of the _gus
        self.assertTrue(wb_tip.has_key('fields'))
        for single_field in self.dummyContext['fields']:
            self.assertTrue(wb_tip['fields'].has_key(single_field['name']))


    @inlineCallbacks
    def test_submission_with_files(self):
        justemptrydb = yield delivery_sched.tip_creation()
        submission_desc = self.dummySubmission
        submission_desc['finalize'] = False
        del submission_desc['submission_gus']
        submission_desc['receivers'] = []

        status = yield submission.create_submission(submission_desc, finalize=False)

        # --- Emulate file upload before assign them to the submission
        yield self.emulate_files_upload(status['submission_gus'])

        # delivery_sched.file_preprocess works only on finalized submission!
        status['finalize'] = True
        status = yield submission.update_submission(status['submission_gus'], status, finalize=True)

        # the files are related to internaltip_id, then appears aligned also if not explicit in the
        # update_submission
        self.assertEqual(len(status['files']), 4)

        # and now check the files
        filesdict = yield delivery_sched.file_preprocess()
        self.assertEqual(len(filesdict), 4)

        processdict = delivery_sched.file_process(filesdict)
        self.assertEqual(len(processdict), 4)

        # Checks the SHA2SUM computed
        for random_f_id, sha2sum in processdict.iteritems():
            sha = SHA256.new()
            sha.update(self.dummyFiles[0]['body'])
            if sha2sum == sha.hexdigest():
                continue

            sha = SHA256.new()
            sha.update(self.dummyFiles[1]['body'])
            if sha2sum == sha.hexdigest():
                continue

            self.assertTrue(False) # Checksum expected unable to be computed

        # Create receiver Tip, for the only receiver present in the context
        new_rtip = yield delivery_sched.tip_creation()
        self.assertEqual(len(new_rtip), 1)

        # generate two receiverfile (one receiver, two file), when submission is completed
        receiverfile_list = yield delivery_sched.receiver_file_align(filesdict, processdict)
        self.assertEqual(len(receiverfile_list), 4)

        # it's used : get_files_receiver(receiver_id, tip_id)
        receiver_files = yield tip.get_files_receiver(status['receivers'][0], new_rtip[0])
        self.assertEqual(len(receiver_files), 4)


    def get_new_receiver_desc(self, descpattern):
        new_r = dict(self.dummyReceiver)
        new_r['name'] = new_r['description'] = new_r['username'] =\
        new_r['notification_fields']['mail_address'] = unicode("%s@%s.xxx" % (descpattern, descpattern))
        new_r['password'] = u'not missing!'
        return new_r

    @inlineCallbacks
    def test_submission_with_receiver_selection(self):

        yield create_receiver(self.get_new_receiver_desc("second"))
        yield create_receiver(self.get_new_receiver_desc("third"))
        yield create_receiver(self.get_new_receiver_desc("fourth"))

        # for some reason, the first receiver is no more with the same ID
        self.receivers = yield get_receiver_list()

        self.assertEqual(len(self.receivers), 4)

        self.dummyContext['receivers'] = [ self.receivers[0]['receiver_gus'],
                                           self.receivers[1]['receiver_gus'],
                                           self.receivers[2]['receiver_gus'],
                                           self.receivers[3]['receiver_gus'] ]
        self.dummyContext['selectable_receiver'] = True
        self.dummyContext['escalation_threshold'] = 0

        context_status = yield update_context(self.dummyContext['context_gus'], self.dummyContext)

        # Create a new request with selected three of the four receivers
        submission_request= self.dummySubmission
        # submission_request['context_gus'] = context_status['context_gus']
        submission_request['submission_gus'] = submission_request['id'] = ''
        submission_request['finalize'] = False
        submission_request['receivers'] = [ self.receivers[0]['receiver_gus'],
                                            self.receivers[1]['receiver_gus'],
                                            self.receivers[2]['receiver_gus'] ]

        status = yield submission.create_submission(submission_request, finalize=False)
        just_empty_eventually_internaltip = yield delivery_sched.tip_creation()

        # Checks, the submission need to be the same now
        self.assertEqual(len(submission_request['receivers']), len(status['receivers']))

        status['finalize'] = True
        submission_request['context_gus'] = context_status['context_gus'] # reused
        status['receivers'] = [ self.receivers[0]['receiver_gus'],
                                self.receivers[3]['receiver_gus'] ]

        status = yield submission.update_submission(status['submission_gus'], status, finalize=True)

        receiver_tips = yield delivery_sched.tip_creation()
        self.assertEqual(len(receiver_tips), len(status['receivers']))


    @inlineCallbacks
    def test_update_submission(self):
        submission_desc = self.dummySubmission
        submission_desc['finalize'] = False
        submission_desc['context_gus'] = self.dummyContext['context_gus']
        submission_desc['submission_gus'] = submission_desc['id'] = submission_desc['mark'] = None

        status = yield submission.create_submission(submission_desc, finalize=False)

        status['wb_fields'] = self.fill_random_fields(self.dummyContext)
        status['finalize'] = True

        status = yield submission.update_submission(status['submission_gus'], status, finalize=True)

        receipt = yield submission.create_whistleblower_tip(status)
        wb_access_id = yield authentication.login_wb(receipt)

        wb_tip = yield tip.get_internaltip_wb(wb_access_id)

        self.assertTrue(wb_tip.has_key('fields'))
        for single_field in self.dummyContext['fields']:
            self.assertTrue(wb_tip['fields'].has_key(single_field['name']))


    @inlineCallbacks
    def test_unable_to_access_finalized(self):
        submission_desc = self.dummySubmission
        submission_desc['finalize'] = True
        submission_desc['context_gus'] = self.dummyContext['context_gus']

        status = yield submission.create_submission(submission_desc, finalize=True)
        try:
            yield submission.update_submission(status['submission_gus'], status, finalize=True)
        except errors.SubmissionConcluded:
            self.assertTrue(True)
            return
        self.assertTrue(False)

        # self.assertRaises(errors.SubmissionConcluded,
        #   (yield submission.update_submission(status['submission_gus'], status, finalize=True)) )
