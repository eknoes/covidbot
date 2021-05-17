import aiohttp_jinja2
import jinja2
from aiohttp import web
from aiohttp.web_exceptions import HTTPNotFound, HTTPFound, HTTPBadRequest
from aiohttp.web_request import Request
from mysql.connector import OperationalError

from covidbot.__main__ import get_connection, parse_config
from feedback.feedback_manager import FeedbackManager

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
    communication = None

    status = None
    if 'status' in request.query:
        status = request.query['status']

    if request.match_info.get("user_id"):
        user_id = int(request.match_info.get("user_id"))
        for s, comm in [("unread", comm_unread), ("read", comm_read), ("answered", comm_answered)]:
            for c in comm:
                if c.user_id == user_id:
                    user = c
                    communication = comm

                    if status:
                        status = s
                    break
        if not user:
            raise HTTPNotFound()
    else:
        if status == "read":
            communication = comm_read
        elif status == "answered":
            communication = comm_answered
        elif status == "unread":
            communication = comm_unread
        else:
            communication = comm_unread + comm_read + comm_answered

    active_tag = None
    if 'tag' in request.query:
        communication = list(filter(lambda x: request.query['tag'] in x.tags, communication))
        active_tag = request.query['tag']

    if communication and not user:
        user = communication[0]

    return {'messagelist': communication, 'user': user, 'base_url': base_url, 'num_unread': len(comm_unread),
            'available_tags': user_manager.get_available_tags(), 'active_status': status, 'active_tag': active_tag}


@routes.post(base_url + r"/user/{user_id:\d+}")
@routes.post(base_url + "/")
async def post_user(request: Request):
    form = await request.post()
    user_id = form.get('user_id')
    if not user_id:
        raise HTTPBadRequest(reason="You need to set a user_id")

    user_id = int(user_id)
    if form.get('mark_read'):
        user_manager.mark_user_read(user_id)
    elif form.get('mark_unread'):
        user_manager.mark_user_unread(user_id)
    elif form.get('reply'):
        user_manager.message_user(user_id, form.get('message'))
        user_manager.mark_user_read(user_id)
    elif form.get('remove_tag'):
        user_manager.remove_user_tag(user_id, form.get('remove_tag'))
    elif form.get('add_tag'):
        user_manager.add_user_tag(user_id, form.get('add_tag'))
        user_manager.mark_user_read(user_id)
    else:
        raise HTTPBadRequest(reason="You have to make some action")

    if request.query:
        raise HTTPFound(base_url + "/?" + request.query_string)
    raise HTTPFound(request.path_qs)


def run():
    app = web.Application()
    app.add_routes(routes)
    app.add_routes([web.static(base_url + '/static', 'resources/feedback-templates/static')])
    aiohttp_jinja2.setup(app,
                         loader=jinja2.FileSystemLoader('resources/feedback-templates/'))
    web.run_app(app, port=config.getint("FEEDBACK", "PORT", fallback=8080))


if __name__ == "__main__":
    run()
