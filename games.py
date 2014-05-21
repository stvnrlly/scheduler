import os, json
from datetime import datetime
from sqlite3 import dbapi2 as sqlite3
from urllib2 import Request, urlopen, URLError
from flask import Flask, request, session, g, redirect, url_for, abort, \
    render_template, flash
from flask.ext.wtf import Form
from flask_wtf.csrf import CsrfProtect
from flask_oauth import OAuth
from wtforms import BooleanField, TextField, TextAreaField, PasswordField, \
    HiddenField, validators
from wtforms.ext.dateutil.fields import DateField, DateTimeField
from sqlalchemy import Column, Integer, String, ForeignKey, create_engine, exc
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Create the application
csrf = CsrfProtect()
app = Flask(__name__)
csrf.init_app(app)
oauth = OAuth()

exec(compile(open("creds.py").read(), "creds.py", 'exec'))
# GOOGLE_CLIENT_ID stored in creds.py
# GOOGLE_CLIENT_SECRET stored in creds.py
REDIRECT_URI = '/oauth2callback'

# Load default config and override config from an environment variable
app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'games.db'),
    DEBUG=True,
    SECRET_KEY='development key',
    USERNAME='admin',
    PASSWORD='default',
))
app.config.from_envvar('GAMES_SETTINGS', silent=True)

# Set up the database

engine = create_engine('sqlite:///games.db', convert_unicode=True)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

google = oauth.remote_app('google',
                          base_url='https://www.google.com/accounts/',
                          authorize_url='https://accounts.google.com/o/oauth2/auth',
                          request_token_url=None,
                          request_token_params={'scope': 'https://www.googleapis.com/auth/userinfo.email',
                                                'response_type': 'code'},
                          access_token_url='https://accounts.google.com/o/oauth2/token',
                          access_token_method='POST',
                          access_token_params={'grant_type': 'authorization_code'},
                          consumer_key=GOOGLE_CLIENT_ID,
                          consumer_secret=GOOGLE_CLIENT_SECRET)

class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    date = Column(String, nullable=False)
    time = Column(String, nullable=False)
    location = Column(String, nullable=False)
    host = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(String)
    minimum = Column(Integer)
    maximum = Column(Integer)
    added_by = Column(String)

    def __init__(self, date, time, location, host, title, description, minimum, maximum, added_by):
        self.date = date
        self.time = time
        self.location = location
        self.host = host
        self.title = title
        self.description = description
        self.minimum = minimum
        self.maximum = maximum
        self.added_by = added_by

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    role = Column(String)
    email = Column(String, unique=True)
    oauth_token = Column(String)

class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    email_changes = Column(Integer, nullable=False)
    added_by = Column(String)

    def __init__(self, name, email_changes, event_id, added_by):
        self.name = name
        self.email_changes = email_changes
        self.event_id = event_id
        self.added_by = added_by

def init_db():
    Base.metadata.create_all(bind=engine)

# Create classes for WTForms

class NewEvent(Form):
    date = DateField('date', [validators.Required()])
    time = TextField('time', [validators.Required()])
    location = TextField('location', [validators.Required()])
    host = TextField('host', [validators.Required()])
    title = TextField('title', [validators.Optional()])
    description = TextAreaField('description', [validators.Optional()])
    minimum = TextField('minimum', [validators.Optional()])
    maximum = TextField('maximum', [validators.Optional()])

class NewPlayer(Form):
    name = TextField('name', [validators.Required()])
    email_changes = BooleanField('email_changes', [validators.Optional()])
    event_id = HiddenField('event_id', [validators.Required()])

class RemovePlayer(Form):
    id = HiddenField('id')

class EditEvent(Form):
    id = HiddenField('id')
    date = DateField('date', [validators.Required()])
    time = TextField('time', [validators.Required()])
    location = TextField('location', [validators.Required()])
    host = TextField('host', [validators.Required()])
    title = TextField('title', [validators.Optional()])
    description = TextAreaField('description', [validators.Optional()])
    minimum = TextField('minimum', [validators.Optional()])
    maximum = TextField('maximum', [validators.Optional()])

# Make sure to close the database properly

@app.after_request
def after_request(response):
    db_session.remove()
    return response

# Create views

@app.route('/', methods=['GET','POST'])
@app.route('/games', methods=['GET','POST'])
def games():
    user = session.get('user')
    user = User.query.filter(User.id == user).first()
    events = []
    for event in Event.query.all():
        date = datetime.strptime(event.date, '%Y-%m-%d')
        if date >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0):
            events.append(event)
        event.date = datetime.strftime(date, '%B %d, %Y')
    events = sorted(events, key=lambda event: event.date)
    players = {}
    adders = {}
    for player in Player.query.all():
        try:
            players[player.event_id].append(player)
            adders[player.event_id].append(player.added_by)
        except KeyError:
            players[player.event_id] = []
            players[player.event_id].append(player)
            adders[player.event_id] = []
            adders[player.event_id].append(player.added_by)
    new_event = NewEvent(request.form)
    new_player = NewPlayer(request.form)
    remove_player = RemovePlayer(request.form)
    edit_event = EditEvent(request.form)
    return render_template('index.html', user=user, events=events, players=players, adders=adders, new_event=new_event, \
                            new_player=new_player, remove_player=remove_player, edit_event=edit_event)

@app.route('/login')
def login():
    callback=url_for('authorized', _external=True)
    return google.authorize(callback=callback)

@app.route('/logout')
def logout():
    session.pop('user')
    return redirect(url_for('games'))

@app.route(REDIRECT_URI)
@google.authorized_handler
def authorized(resp):
    access_token = resp['access_token']
#    session['access_token'] = access_token, ''
    headers = {'Authorization': 'OAuth '+access_token}
    req = Request('https://www.googleapis.com/oauth2/v1/userinfo',
                  None, headers)
    try:
        res = urlopen(req)
    except URLError, e:
        if e.code == 401:
            # Unauthorized - bad token
            session.pop('access_token', None)
            return redirect(url_for('login'))
        user = res.read()
    info = json.loads(res.read())
    user = User.query.filter(User.oauth_token == info['id']).first()
    if user == None:
        user = User(name = info['name'], email = info['email'], oauth_token = info['id'], role='user')
        db_session.add(user)
        db_session.commit()
        db_session.flush()
    session['user'] = user.id
    return redirect(url_for('games'))

@google.tokengetter
def get_access_token():
    return session.get('access_token')

@app.route('/add_event', methods=['POST'])
def add_event():
    new_event = NewEvent(request.form)
    if new_event.validate_on_submit():
        event = Event(new_event.date.data, new_event.time.data, new_event.location.data, \
                new_event.host.data, new_event.title.data, new_event.description.data, \
                new_event.minimum.data, new_event.maximum.data, added_by=user.oauth_token)
        db_session.add(event)
        db_session.commit()
        db_session.flush()
        flash('New event was successfully created')
    else:
        flash(new_event.errors)
    return redirect('/games')

@app.route('/add_player', methods=['POST'])
def add_player():
    new_player = NewPlayer(request.form)
    user = session.get('user')
    user = User.query.filter(User.id == user).first()
    if new_player.validate_on_submit():
        try:
            player = Player(new_player.name.data, new_player.email_changes.data, new_player.event_id.data, added_by=user.oauth_token)
            db_session.add(player)
            db_session.commit()
            db_session.flush()
            event = Event.query.filter(Event.id == new_player.event_id.data).first()
            text = ''
            for d in event.title.split():
                text += d
                text += '+'
            text = text[:len(text)-1]
            date = datetime.strptime(event.date + event.time, '%Y-%m-%d%I:%M%p')
            date = datetime.strftime(date, '%Y%m%dT%H%M%S')
            details = ''
            for d in event.description.split():
                details += d
                details += '+'
            details = details[:len(details)-1]
            location = ''
            for d in event.location.split():
                location += d
                location += '+'
            location = location[:len(location)-1]
            flash("Success! <a href='https://www.google.com/calendar/render?action=TEMPLATE&text="+text+"&dates="+date+"/"+date+"&details="+details+"&location="+location+"&sf=true&output=xml'>Add to Google Calendar?</a>")
        except exc.SQLAlchemyError:
            flash("You've already added that person! Try another name.")
    else:
        flash(new_player.errors)
    return redirect('/games')

@app.route('/remove_player', methods=['POST'])
def remove_player():
    remove_player = RemovePlayer(request.form)
    if remove_player.validate_on_submit():
        player = Player.query.filter(Player.id == remove_player.id.data).first()
        db_session.delete(player)
        db_session.commit()
        db_session.flush()
        flash('Successfully removed.')
    else:
        flash(remove_player.errors)
    return redirect('/games')

@app.route('/edit_event', methods=['POST'])
def edit_event():
    edit_event = EditEvent(request.form)
    if edit_event.validate_on_submit():
        event = Event.query.filter(Event.id == edit_event.id.data).first()
        event.date = edit_event.date.data
        event.time = edit_event.time.data
        event.location = edit_event.location.data
        event.host = edit_event.host.data
        event.title = edit_event.title.data
        event.description = edit_event.description.data
        event.minimum = edit_event.minimum.data
        event.maximum = edit_event.maximum.data
        db_session.commit()
        db_session.flush()
        flash('Event was successfully edited')
    else:
        flash(edit_event.errors)
    return redirect('/games')

# Run the application

if __name__ == '__main__':
    init_db()
    app.run()
