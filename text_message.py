from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
)

import configparser
import enum
import random
import redis
import redis_lock
import sys
sys.path.append('./bin')
import time
from scrape_sonet import *
from scrape_cygame import *

from arena import *
from clan import *
from clan_sheet import *
from cloud_firestore import *
from imgur import *
from keyword_reply import *
from scrape_sonet import *
from subscribe import *


config = configparser.ConfigParser()
config.read('config.ini')
# Channel Access Token
line_bot_api = LineBotApi(config.get('line-bot', 'channel_access_token'))
# Channel Secret
handler = WebhookHandler(config.get('line-bot', 'channel_secret'))

r = redis.from_url(os.environ['REDIS_URL'], decode_responses=True)
# r = redis.StrictRedis(decode_responses=True)

class StrEnum(str, enum.Enum):
     pass
class MsgType(StrEnum):
    Atk = '1'
    Def = '0'

def strQ2B(text):

    ss = []
    for s in text:
        string = ''
        for uchar in s:
            inside_code = ord(uchar)
            # Transfer fullwidth space to halfwidth space
            if inside_code == 12288:
                inside_code = 32
            # Transfer fullwidth string to halfwidth string except space
            elif (inside_code >= 65281 and inside_code <= 65374):
                inside_code -= 65248
            string += chr(inside_code)
        ss.append(string)
        
    return ''.join(ss)


def get_user_text_msg_info(event):

    msg = event.message.text
    user_id = event.source.user_id
    profile = line_bot_api.get_profile(user_id)
    user_name = profile.display_name

    return msg, user_id, user_name 


def get_group_text_msg_info(event):

    msg = event.message.text
    group_id = event.source.group_id
    user_id = event.source.user_id
    group_profile = line_bot_api.get_group_member_profile(group_id, user_id)
    user_name = group_profile.display_name

    return msg, group_id, user_id, user_name 


def get_room_text_msg_info(event):

    msg = event.message.text
    room_id = event.source.room_id
    user_id = event.source.user_id
    profile = line_bot_api.get_room_member_profile(room_id, user_id)
    user_name = profile.display_name
    return msg, room_id, user_id, user_name


def handle_user_arena_text_message(user_id, msg):

    reply_msg = ''
    key = user_id
    status = r.get(key + 'status')
    r.delete(key + 'status')
    if status != 'True':
        return reply_msg

    our = r.lrange(key + "our", 0, -1)
    for i in range(len(our)):
        our[i] = int(our[i])
    enemy = r.lrange(key + "enemy", 0, -1)
    for i in range(len(enemy)):
        enemy[i] = int(enemy[i])

    win = r.get(key + 'win')
    if msg == '??????' or msg == MsgType.Def:
        if win == 'True':
            win = False
        else:
            win = True
        our, enemy = enemy, our
    if msg == '??????' or msg == MsgType.Atk:
        if win == 'True':
            win = True
        else:
            win = False

    if len(our) == 0 or len(enemy) == 0:
        reply_msg = '???????????????'
        return reply_msg

    find_status = find_arena_record(our, enemy, win, user_id)
    if find_status == 'repeated':
        reply_msg = '????????????????????????????????????????????????'
        return reply_msg

    reply_msg = get_record_msg(our, enemy, win, find_status)    
    return reply_msg


def user_find_str_processing(user_id, msg):

    reply_msg = '????????????????????????????????????'

    if msg == '??????':
        reply_msg = scrape_pcrd_sonet()

    if msg == '??????':
        reply_msg = scrape_pcrd_cygame()

    if '??????: ' in msg:
        msg = msg.replace('??????: ', '')
        status, enemy = nickname_search_arena_record(msg)
        if status == 'True':
            enemy = sort_character_loc(enemy)
            reply_msg = get_user_search_record(enemy, user_id)
        else:
            reply_msg = status
            
        return reply_msg

    if '????????????' == msg:
        status = get_user_arena_database(user_id)
        if status == True:
            method = '???????????????'
        else:
            method = '???????????????'
        reply_msg = '??????????????????????????????: ' + method

    if '????????????:' in msg :
        msg = msg.replace('????????????:', '')
        if msg == '??????':
            status = True
        elif msg == '??????':
            status = False
        else:
            reply_msg = '???????????????????????????????????????'
            return reply_msg
        update_user_arena_database(user_id, status)
        reply_msg = '????????????????????????????????????: ' + msg + '?????????'

    return reply_msg


def handle_user_text_message(event):

    reply_msg = ''
    msg, user_id, user_name = get_user_text_msg_info(event)

    msg = strQ2B(msg)
    if msg == '??????' or msg == MsgType.Atk or msg == '??????' or msg == MsgType.Def:
        reply_msg = handle_user_arena_text_message(user_id, msg)
        return reply_msg

    if '!' == msg[0]:
        msg = msg[1:]
        reply_msg = user_find_str_processing(user_id, msg)
        return reply_msg
    if '#' == msg[0]:
        if clan_period():
            info = get_user_info(user_id)
            try:
                karyl_group = ['C423cd7dee7263b3a2db0e06ae06d095e', 'C1f08f2cc641df24f803b133691e46e92']
                karyl_group.index(info['group_id'])
                msg = msg[1:]
                reply_msg = clan_user_str_processing(user_id, msg)
            except ValueError:
                reply_msg = '??????????????????????????????????????????????????????????????????'
        else:
            reply_msg = '?????????????????????????????????????????????'
        return reply_msg
    if '@' == msg[0]:
        msg = msg[1:]
        reply_msg = subscribe_str_processing(msg, user_id)
        send_msg = TextSendMessage(text= reply_msg )
        line_bot_api.reply_message(event.reply_token, send_msg)
        reply_msg = ''
        return reply_msg
    
    reply_msg = handle_key_message(event) 
    return reply_msg


def handle_group_upload(group_id, user_id, msg):

    key = group_id + user_id
    redis_our = r.lrange(key + "our", 0, -1)
    redis_enemy = r.lrange(key + "enemy", 0, -1)
    win = r.get(key + 'win')

    our = [0] * len(redis_our)
    enemy = [0] * len(redis_enemy)
    if msg == '??????' or msg == MsgType.Def:
        for i in range(len(redis_our)):
            enemy[i] = int(redis_our[i])
        for i in range(len(redis_enemy)):
            our[i] = int(redis_enemy[i])
        if win == 'True':
            win = False
        else:
            win = True
    if msg == '??????' or msg == MsgType.Atk:
        for i in range(len(redis_our)):
            our[i] = int(redis_our[i])
        for i in range(len(redis_enemy)):
            enemy[i] = int(redis_enemy[i])
        if win == 'True':
            win = True
        else:
            win = False

    if our == [] or enemy == []:
        reply_msg = '???????????????'
        return reply_msg

    find_status = find_group_arena_record(our, enemy, win, group_id)
    if find_status == 'success':
        reply_msg = get_group_record_msg(our, enemy, win, find_status)

    return reply_msg


def handle_group_3v3_upload(group_id, user_id, msg):

    key = group_id + user_id
    count = r.get(key + 'count')
    if not count:
        reply_msg = '???????????????'
        return reply_msg

    for record in range(int(count)):
        redis_our = r.lrange(key + 'our' + str(record), 0, -1)
        redis_enemy = r.lrange(key + 'enemy' + str(record), 0, -1)
        win = r.get(key + 'win' + str(record))
        
        our = [0] * len(redis_our)
        enemy = [0] * len(redis_enemy)
        if msg == '??????' or msg == MsgType.Def:
            for i in range(len(redis_our)):
                enemy[i] = int(redis_our[i])
            for i in range(len(redis_enemy)):
                our[i] = int(redis_enemy[i])
            if win == 'True':
                win = False
            else:
                win = True
        if msg == '??????' or msg == MsgType.Atk:
            for i in range(len(redis_our)):
                our[i] = int(redis_our[i])
            for i in range(len(redis_enemy)):
                enemy[i] = int(redis_enemy[i])
            if win == 'True':
                win = True
            else:
                win = False
        
        find_status = find_group_arena_record(our, enemy, win, group_id)
        if find_status == 'success':
            reply_msg = get_group_record_msg(our, enemy, win, find_status)

    return reply_msg


def handle_group_arena_text_message(group_id, user_id, msg):
    
    reply_msg = ''
    key = group_id + user_id
    status = r.get(key + 'status')
    r.delete(key + 'status')
    if status != 'True':
        return reply_msg

    mode = r.get(key + 'mode')
    r.delete(key + 'mode')
    if mode == 'Upload':
        reply_msg = handle_group_upload(group_id, user_id, msg)
    if mode == '3v3':
        reply_msg = handle_group_3v3_upload(group_id, user_id, msg)

    return reply_msg


def handle_group_text_search(group_id, msg):

    msg = msg.replace('??????: ', '')
    reply_msg , enemy = nickname_search_arena_record(msg)
    if reply_msg == 'True':
        enemy = sort_character_loc(enemy)

        record, good, bad = search_group_arena_record(enemy, group_id)
        record, good, bad = sort_arena_record(record, good, bad)
        if len(record) > 0:
            reply_img = create_group_record_img(record, good, bad)
            url = get_nacx_image(reply_img)
            return url
        else:
            reply_msg = '????????????????????????'
            return reply_msg
    else:
        return reply_msg


def get_group_character_star(group_id, msg):

    reply_msg = ''
    msg = msg.replace('????????????', '')
    status = get_group_arena_utmost_star(group_id)
    if not status:
        reply_msg = ''
    if status == True:
        reply_msg = '???????????????????????????: ??????'
    else:
        reply_msg = '???????????????????????????: ??????'

    return reply_msg


def handle_group_character_star(group_id, msg):

    reply_msg = ''
    msg = msg.replace('??????: ', '')
    if msg == '??????':
        status = False
    elif msg == '??????':
        status = True
    else:
        reply_msg = '???????????????????????????????????????'
        return reply_msg
    update_group_arena_utmost_star(group_id, status)
    reply_msg = '???????????????????????????????????????: ' + msg

    return reply_msg

def handle_group_text_message(event):

    reply_msg = ''
    msg, group_id, user_id, user_name = get_group_text_msg_info(event)

    msg = strQ2B(msg)
    if msg == '??????' or msg == '1' or msg == '??????' or msg == '0':
        reply_msg = handle_group_arena_text_message(group_id, user_id, msg)
        return reply_msg

    if '!' == msg[0]:
        msg = msg[1:]
        if '??????: ' in msg:
            reply_msg = handle_group_text_search(group_id, msg)
        elif '????????????' == msg:
            reply_msg = get_group_character_star(group_id, msg)
        elif '??????: ' in msg:
            reply_msg = handle_group_character_star(group_id, msg)
        elif msg == '??????':
            reply_msg = scrape_pcrd_sonet()
        elif msg == '??????':
            reply_msg = scrape_pcrd_cygame()
        else:
            try:
                karyl_group = ['C423cd7dee7263b3a2db0e06ae06d095e', 'C1f08f2cc641df24f803b133691e46e92']
                karyl_group.index(group_id)
            except ValueError:
                reply_msg = '????????????????????????????????????????????????????????????????????????'
                return reply_msg

            reply_msg = clan_group_find_str_processing(group_id, user_id, user_name, msg)
        
        return reply_msg

    if '#' == msg[0]:
        try:
            karyl_group = ['C423cd7dee7263b3a2db0e06ae06d095e', 'C1f08f2cc641df24f803b133691e46e92']
            karyl_group.index(group_id)
        except ValueError:
            reply_msg = '????????????????????????????????????????????????????????????????????????'
            return reply_msg
        
        group_member = get_group_member(group_id)
        try:
            group_member[user_name]

            msg = msg[1:]
            # lock = redis_lock.Lock(r, 'clan_sheet')
            # redis_lock.reset_all(r)
            # while lock.get_owner_id() == user_id or not lock.acquire(blocking = False):
            # print('Wait Lock. name=', user_name)
            # while not lock.acquire(blocking = True, timeout = 4):
            # #     time.sleep(0.01)
            # print('Got Lock. name=', user_name)
            reply_msg = clan_group_set_str_processing(group_id, user_id, user_name, msg)
            # lock.release()

            # if clan_period():
            # else:
            #     reply_msg = '???????????????????????????????????????'
        except KeyError:
            reply_msg = user_name + '????????????????????????????????????????????????'

        return reply_msg

    reply_msg = handle_key_message(event)
    return reply_msg


def handle_room_text_message(event):
    
    reply_msg = handle_key_message(event)
    return reply_msg


def handle_key_message(event):

    if event.source.type == 'group':
        msg, group_id, user_id, user_name  = get_group_text_msg_info(event)
    if event.source.type == 'user':
        msg, user_id, user_name = get_user_text_msg_info(event)
    if event.source.type == 'room':
        msg, room_id, user_id, user_name = get_room_text_msg_info(event)
    
    # msg = event.message.text
    image_key = ['????????????', '??????', '?????????', '?????????', '??????', '??????', '??????']
    reply_msg = ''

    ##########  Image reply  ##########
    for key in image_key:
        if key in msg:
            print('?????????: %s' % (key))
            url = get_album_image(key)
            return url

    ##########  Text reply  ##########
    if '??????' in msg:
        reply_msg = get_key_msg(msg, user_name)
        return reply_msg

    ##########  Sticker reply  ##########
    sticker_key = ['???', '??????', '??????', '??????', '??????', '??????', '??????', '???', 
            '??????', '??????', '?????????', '????', '??????', '?????????!', '?????????', '??????',
            '??????', '??????', '??????', '??????', '??????', '??????????????????', '??????', '???',
            '??????', '??????', '?????????', 
            '??????', '??????', '?????????', '???????????????', '????????????', '???', '??????', '??????']

    for index, sticker in enumerate(sticker_key):
        if sticker in msg:
            url = get_key_sticker(index)
            return url

    return reply_msg
