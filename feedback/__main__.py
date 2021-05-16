import aiohttp_jinja2
import jinja2
from aiohttp.web_exceptions import HTTPNotFound, HTTPFound
from aiohttp.web_request import Request

from covidbot.__main__ import get_connection, parse_config

from aiohttp import web

from feedback.feedback_manager import FeedbackManager

routes = web.RouteTableDef()
config = parse_config('config.ini')
connection = get_connection(config, autocommit=True)
user_manager = FeedbackManager(connection)


@routes.get(r"/user/{user_id:\d+}")
@routes.get("/")
@aiohttp_jinja2.template('single.jinja2')
async def show_user(request):
    communication = user_manager.get_all_communication()

    user_id = request.match_info.get("user_id")
    if not user_id:
        user_id = str(communication[0].user_id)

    user = None
    for c in communication:
        if str(c.user_id) == user_id:
            user = c
            break

    if not user:
        raise HTTPNotFound()

    return {'messagelist': communication, 'user': user}


@routes.post(r"/user/{user_id:\d+}")
async def post_user(request: Request):
    user_id = int(request.match_info["user_id"])
    form = await request.post()
    if form.get('mark_read'):
        user_manager.mark_user_read(user_id)
    elif form.get('mark_unread'):
        user_manager.mark_user_unread(user_id)
    elif form.get('reply'):
        user_manager.message_user(user_id, form.get('reply-message'))
    raise HTTPFound(f'/user/{request.match_info["user_id"]}')


def run():
    app = web.Application()
    app.add_routes(routes)
    app.add_routes([web.static('/static', 'resources/feedback-templates/static')])
    aiohttp_jinja2.setup(app,
                         loader=jinja2.FileSystemLoader('resources/feedback-templates/'))
    web.run_app(app)


if __name__ == "__main__":
    run()
