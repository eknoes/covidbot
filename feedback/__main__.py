import aiohttp_jinja2
import jinja2
from aiohttp.web_exceptions import HTTPNotFound, HTTPFound, HTTPBadRequest
from aiohttp.web_request import Request
from mysql.connector import OperationalError

from covidbot.__main__ import get_connection, parse_config

from aiohttp import web

from feedback.feedback_manager import FeedbackManager, CommunicationState

routes = web.RouteTableDef()
config = parse_config('config.ini')
connection = get_connection(config, autocommit=True)
user_manager = FeedbackManager(connection)
base_url = config.get('FEEDBACK', 'BASE_URL', fallback='')


@routes.get(base_url + r"/user/{user_id:\d+}")
@routes.get(base_url + "/")
@aiohttp_jinja2.template('single.jinja2')
async def show_user(request: Request):
    try:
        comm_unread, comm_read, comm_answered = user_manager.get_all_communication()
    except OperationalError as e:
        global connection
        if connection:
            connection.close()

        connection = get_connection(config, autocommit=True)
        user_manager.connection = connection
        comm_unread, comm_read, comm_answered = user_manager.get_all_communication()

    user = None
    communication = comm_unread

    if request.match_info.get("user_id"):
        user_id = int(request.match_info.get("user_id"))
        for s, comm in [("unread", comm_unread), ("read", comm_read), ("answered", comm_answered)]:
            for c in comm:
                if c.user_id == user_id:
                    user = c
                    communication = comm
                    break
        if not user:
            raise HTTPNotFound()

    else:
        status = ""
        if 'status' in request.query:
            status = request.query['status']

        if status == "read":
            communication = comm_read
        elif status == "answered":
            communication = comm_answered
        elif status == "unread":
            communication = comm_unread
        else:
            communication = comm_unread + comm_read + comm_answered

    if 'tag' in request.query:
        communication = list(filter(lambda x: request.query['tag'] in x.tags, communication))

    if communication and not user:
        user = communication[0]

    return {'messagelist': communication, 'user': user, 'base_url': base_url, 'num_unread': len(comm_unread),
            'available_tags': user_manager.get_available_tags()}


@routes.post(base_url + r"/user/{user_id:\d+}")
async def post_user(request: Request):
    user_id = int(request.match_info["user_id"])
    form = await request.post()
    if form.get('mark_read'):
        user_manager.mark_user_read(user_id)
    elif form.get('mark_unread'):
        user_manager.mark_user_unread(user_id)
    elif form.get('reply'):
        user_manager.message_user(user_id, form.get('message'))
    elif form.get('add_tag'):
        user_manager.add_user_tag(user_id, form.get('add_tag'))
        raise HTTPFound(base_url + f'/user/{request.match_info["user_id"]}?tag={form.get("add_tag")}')
    else:
        raise HTTPBadRequest(reason="You have to make some action")
    raise HTTPFound(base_url + f'/user/{request.match_info["user_id"]}')


def run():
    app = web.Application()
    app.add_routes(routes)
    app.add_routes([web.static(base_url + '/static', 'resources/feedback-templates/static')])
    aiohttp_jinja2.setup(app,
                         loader=jinja2.FileSystemLoader('resources/feedback-templates/'))
    web.run_app(app, port=config.getint("FEEDBACK", "PORT", fallback=8080))


if __name__ == "__main__":
    run()
