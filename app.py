#!/usr/bin/env python
# -*- coding: utf-8 -*-

# app.py
import os
import time
from bottle import abort, route, run, request,Bottle, response, static_file, template
# import pymysql.cursors
import json
from datetime import datetime, timedelta
import subprocess
app = Bottle()


# 
handlers = {}


PORT = 9000

isPrivate = False

@app.route("/video")
def get_video():
    # Return limit exceeded if 4 applications are already open
    appid = -1
    for key in handlers.keys():
        if(handlers[key].getClientCount()==0):
            appid = key
            break

    if(appid == -1):
        for i in range(1,5):
            if(i not in handlers.keys()):
                appid = i
                break
    if(appid == -1):
        return "Connection limit exceeded, only a maximum of 4 connections can be made simultaneously"

    # Launch the Unity executable file
    unity_exe_path = 'E:/Projects/SteamingTest/Build/Window/SteamingTest.exe'  # Replace with the path to your Unity executable file
    unity_args = ["-appid",str(appid)]
    subprocess.Popen([unity_exe_path] + unity_args)
    # appid = 1

    context = {
        'appid': appid
    }
    html = template('receiver/index.html', **context)
    return html

@app.route('/static/<filepath:path>')
def serve_static(filepath):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    static_folder = os.path.join(current_dir, 'static')
    return static_file(filepath, root=static_folder)

@app.route('/config')
def server_config():
    data ={"useWebSocket":True,"startupMode":"public","logging":"dev"}
    json_data = json.dumps(data)
    return json_data



@app.route('/<appid:int>')
def handle_websocket(appid):
    wsock = request.environ.get('wsgi.websocket')
    if not wsock:
        html = template('index/index.html')
        return html
    # Handle the connection establishment event
    handler = getOrCreateHandler(appid)
    handler.addClient(wsock)
    print("WebSocket connected")
    while True:
        try:
            message = wsock.receive()
            print(message)
            if(message==None):
                break
            else:
                msg = json.loads(message)
                msg_type = msg["type"]

                if msg_type == "connect":
                    handler.onConnect(wsock, msg["connectionId"])
                elif msg_type == "disconnect":
                    handler.onDisconnect(wsock, msg["connectionId"])
                elif msg_type == "offer":
                    handler.onOffer(wsock, msg["data"])
                elif msg_type == "answer":
                    handler.onAnswer(wsock, msg["data"])
                elif msg_type == "candidate":
                    handler.onCandidate(wsock, msg["data"])
                else:
                    pass
        except WebSocketError:
            break

    # Handle the connection closure event
    handler.removeClient(wsock)
    print("WebSocket disconnected")

def getOrCreateHandler(key):
    if key in handlers:
        return handlers[key]
    else:
        handlers[key] = Handler()
        return handlers[key]

class Handler:
    def __init__(self):
        # [{sessonId:[connectionId,...]}]
        self.clients = {}
        # [{connectionId:[sessionId1, sessionId2]}]
        self.connectionPair = {}

    def onConnect(self, ws, connectionId):
        polite = True
        if isPrivate:
            if connectionId in self.connectionPair:
                pair = self.connectionPair[connectionId]
                if pair[0] is not None and pair[1] is not None:
                    ws.send(json.dumps({ "type": "error", "message": f"{connectionId}: This connection id is already used." }))
                    return
                elif pair[0] is not None:
                    self.connectionPair[connectionId] = [pair[0], ws]
        else:
            self.connectionPair[connectionId] = [ws, None]
            polite = False
        connectionIds = self.getOrCreateConnectionIds(ws)
        connectionIds.add(connectionId)
        data = { "type": "connect", "connectionId": connectionId, "polite":  polite}
        ws.send(json.dumps(data))

    def onDisconnect(self, ws, connectionId):
        connectionIds = self.clients[ws]
        connectionIds.remove(connectionId)
        data = { "type": "disconnect", "connectionId": connectionId }
        if connectionId in self.connectionPair:
            pair = self.connectionPair[connectionId]
            otherSessionWs = pair[0] if pair[0] != ws else pair[1]
            if otherSessionWs:
                otherSessionWs.send(json.dumps(data))
        del self.connectionPair[connectionId]
        ws.send(json.dumps(data))

    def onOffer(self, ws,message):
        connectionId = message["connectionId"]
        time_now = int(time.time() * 1000)
        newOffer = {"sdp":message["sdp"],"datetime":time_now,"polite":False}
        sendData = { "from": connectionId, "to": "", "type": "offer", "data": newOffer }

        if isPrivate:
            if connectionId in self.connectionPair:
                pair = self.connectionPair[connectionId]
                otherSessionWs = pair[0] if pair[0] != ws else pair[1]
                if otherSessionWs:
                    newOffer["polite"] = True
                    otherSessionWs.send(json.dumps(sendData))
        else:
            self.connectionPair[connectionId] = [ws, None]
            for k in self.clients.keys():
                if k != ws:
                    k.send(json.dumps(sendData))

    def onAnswer(self, ws,message):
        connectionId = message["connectionId"]
        time_now = int(time.time() * 1000)
        newAnswer = {"sdp":message["sdp"],"datetime":time_now}
        sendData = { "from": connectionId, "to": "", "type": "answer", "data": newAnswer }
        if connectionId in self.connectionPair:
            pair = self.connectionPair[connectionId]
            otherSessionWs = pair[0] if pair[0] != ws else pair[1]
            if not isPrivate:
                self.connectionPair[connectionId] = [otherSessionWs, ws]
            otherSessionWs.send(json.dumps(sendData))

    def onCandidate(self, ws,message):
        connectionId = message["connectionId"]
        time_now = int(time.time() * 1000)
        candidate = {"candidate":message["candidate"], "sdpMLineIndex":message["sdpMLineIndex"], "sdpMid":message["sdpMid"], "datetime":time_now}
        sendData = { "from": connectionId, "to": "", "type": "candidate", "data": candidate }
        if isPrivate:
            if connectionId in self.connectionPair:
                pair = self.connectionPair[connectionId]
                otherSessionWs = pair[0] if pair[0] != ws else pair[1]
                if otherSessionWs:
                    otherSessionWs.send(json.dumps(sendData))
        else:
            for k in self.clients.keys():
                if k != ws:
                    k.send(json.dumps(sendData))

    def getOrCreateConnectionIds(self, ws):
        if ws in self.clients:
            return self.clients[ws]
        else:
            self.clients[ws] = set()
            return self.clients[ws]
    def addClient(self,ws):
        self.clients[ws] = set()
        
    def removeClient(self,ws):
        self.clients.pop(ws)
        #Send a message to the Unity executable to invoke Application.Quit()
        sendData = {"type": "killApp"}
        for session in self.clients.keys():
            session.send(json.dumps(sendData))

    def getClientCount(self):
        return len(self.clients)

from gevent.pywsgi import WSGIServer
from geventwebsocket import WebSocketError
from geventwebsocket.handler import WebSocketHandler
server = WSGIServer(('127.0.0.1', PORT), app,
                    handler_class=WebSocketHandler)
server.serve_forever()