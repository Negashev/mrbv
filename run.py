import copy
import logging
import os
from random import shuffle
from urllib.parse import urlparse

import gitlab
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from japronto import Application
from joblib import Parallel, delayed
from joblib.parallel import parallel_backend

MRBV_TOKEN = os.getenv('MRBV_TOKEN', None)
if MRBV_TOKEN is None:
    print(f"Please set MRBV_TOKEN")

try:
    o = urlparse(os.getenv('MRBV_URL', None))
    MRBV_URL = f"{o.scheme}://{o.netloc}"
except Exception as e:
    print(f"Error parse MRBV_URL: {e}")

MRBV_REQUIRED_VOTE_IDS = os.getenv('MRBV_REQUIRED_VOTE_IDS', None)
if MRBV_REQUIRED_VOTE_IDS is not None:
    MRBV_REQUIRED_VOTE_IDS = [int(i) for i in os.getenv('MRBV_REQUIRED_VOTE_IDS', '').split(',')]
else:
    MRBV_REQUIRED_VOTE_IDS = []

PROJECTS = []
WITH_UPVOTE = []
PROJECTS_REQUIRED_VOTE_IDS = {}
MERGE_REQUESTS = []
SUBSCRIBE = {}


async def get_projects():
    global PROJECTS
    PROJECTS = gl.projects.list(all=True)
    print(f"found {len(PROJECTS)} projects")


def check_project_upvote(project):
    try:
        MRBV_BOT_UPVOTE = project.variables.get('MRBV_BOT_UPVOTE')
        try:
            MRBV_REQUIRED_VOTE_IDS = [int(i) for i in project.variables.get('MRBV_REQUIRED_VOTE_IDS').value.split(',')]
            print(f"'{project.name_with_namespace}' with {len(MRBV_REQUIRED_VOTE_IDS)} ids for required vote")
        except gitlab.GitlabGetError as e:
            MRBV_REQUIRED_VOTE_IDS = []
        return project, int(MRBV_BOT_UPVOTE.value), MRBV_REQUIRED_VOTE_IDS
    except Exception as e:
        pass


async def get_variables():
    global PROJECTS
    global WITH_UPVOTE
    this_PROJECTS = copy.copy(PROJECTS)
    # issue https://github.com/scikit-learn/scikit-learn/issues/8920
    with parallel_backend('threading'):
        data = Parallel(n_jobs=4)(delayed(check_project_upvote)(project) for project in this_PROJECTS)
        WITH_UPVOTE = [i for i in data if i is not None]
    print(f"found {len(WITH_UPVOTE)} MRBV_BOT_UPVOTE in {len(PROJECTS)} projects")


def check_merge_by_award_emojis(merge, required_vote_ids):
    for award_emoji in merge.awardemojis.list(all=True):
        if award_emoji.name == 'thumbsup' and award_emoji.user['id'] in required_vote_ids:
            return True
    return False


def check_merge_upvote(data):
    global SUBSCRIBE
    project, upvote, required_vote_ids = data
    try:
        mergerequests = []
        for i in project.mergerequests.list(state='opened', all=True):
            # coming soon
            # if i.id not in SUBSCRIBE.keys():
            #     SUBSCRIBE[i.id] = i
            if required_vote_ids:
                check_merge = check_merge_by_award_emojis(i, required_vote_ids)
            else:
                check_merge = True
            if int(i.upvotes) >= int(upvote) and \
                    int(i.downvotes) <= 0 and \
                    not i.work_in_progress and \
                    i.merge_status == 'can_be_merged' and \
                    check_merge:
                mergerequests.append(i)
        return mergerequests
    except Exception as e:
        pass


async def get_merges():
    global WITH_UPVOTE
    global MERGE_REQUESTS
    global PROJECTS
    this_WITH_UPVOTE = copy.copy(WITH_UPVOTE)
    with parallel_backend('threading'):
        data = Parallel(n_jobs=4)(delayed(check_merge_upvote)(data) for data in this_WITH_UPVOTE)
        buff = []
        for mergerequests in [i for i in data if i is not None]:
            buff = buff + mergerequests
        MERGE_REQUESTS = buff
    print(f"found {len(MERGE_REQUESTS)} merges with {len(WITH_UPVOTE)} MRBV_BOT_UPVOTE in {len(PROJECTS)} projects")


# coming soon
async def subscribe():
    global SUBSCRIBE
    this_SUBSCRIBE = copy.copy(SUBSCRIBE)
    for i in this_SUBSCRIBE.keys():
        try:
            print(f"subscribe '{this_SUBSCRIBE[i].title}'")
            this_SUBSCRIBE[i].subscribe()
        except Exception as e:
            pass
        del SUBSCRIBE[i]


def accept(merge):
    name_with_namespace = gl.projects.get(merge.project_id).name_with_namespace
    try:
        merge.merge()
        print(f"merge '{merge.title}' in {name_with_namespace}")
        MERGE_REQUESTS.remove(merge)
    except Exception as e:
        print(f"{e} ===> {merge.title} ({name_with_namespace})")


async def try_close_merge():
    global MERGE_REQUESTS
    this_MERGE_REQUESTS = copy.copy(MERGE_REQUESTS)
    shuffle(this_MERGE_REQUESTS)
    if not this_MERGE_REQUESTS:
        return
    # accept first merge
    accept(this_MERGE_REQUESTS[0])


async def connect_scheduler():
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(get_projects, 'interval', seconds=int(os.getenv('MRBV_SECONDS_PROJECTS', 300)), max_instances=1)
    scheduler.add_job(get_variables, 'interval', seconds=int(os.getenv('MRBV_SECONDS_VARIABLES', 120)), max_instances=1)
    scheduler.add_job(get_merges, 'interval', seconds=int(os.getenv('MRBV_SECONDS_MERGE', 60)), max_instances=1)
    # scheduler.add_job(subscribe, 'interval', seconds=int(os.getenv('MRBV_SECONDS_SUBSCRIBE', 60)), max_instances=1)
    scheduler.add_job(try_close_merge, 'interval', seconds=int(os.getenv('MRBV_SECONDS_MERGE', 30)), max_instances=1)

    scheduler.start()


async def health_check(request):
    global MERGE_REQUESTS
    data = {}
    for i in MERGE_REQUESTS:
        data[i.id] = {"title": i.title, "project_id": i.project_id}
    return request.Response(json=data, mime_type="application/json")


app = Application()
gl = gitlab.Gitlab(MRBV_URL, private_token=MRBV_TOKEN, api_version='4')
logging.getLogger('apscheduler.scheduler').propagate = False
logging.getLogger('apscheduler.scheduler').addHandler(logging.NullHandler())
app.loop.run_until_complete(get_projects())
app.loop.run_until_complete(get_variables())
app.loop.run_until_complete(get_merges())
app.loop.run_until_complete(try_close_merge())
# app.loop.run_until_complete(subscribe())
app.loop.run_until_complete(connect_scheduler())
router = app.router
router.add_route('/', health_check)
app.run(port=80)
