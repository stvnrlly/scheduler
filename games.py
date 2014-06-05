import os, json
from datetime import datetime
from sqlite3 import dbapi2 as sqlite3
from urllib2 import Request, urlopen, URLError
from flask import Flask, request, session, g, redirect, url_for, abort, \
    render_template, flash
from flask.ext.wtf import Form
from flask_wtf.csrf import CsrfProtect
from flask_oauth import OAuth
from flask.ext.mail import Mail, Message
from wtforms import BooleanField, TextField, TextAreaField, PasswordField, \
    HiddenField, validators
from wtforms.ext.dateutil.fields import DateField, DateTimeField
from sqlalchemy import Column, Integer, String, ForeignKey, create_engine, exc
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base

# Create the application
csrf = CsrfProtect()
app = Flask(__name__)
csrf.init_app(app)
oauth = OAuth()
mail = Mail(app)

exec(compile(open("creds.py").read(), "creds.py", 'exec'))
# OAuth credentials stored in creds.py


# Load default config and override config from an environment variable
# Mail settings are stored in creds.py
app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'games.db'),
    DEBUG=True,
    SECRET_KEY='development key',
    USERNAME='admin',
    PASSWORD='default',
    MAIL_SERVER=MAIL_SERVER,
    MAIL_PORT=MAIL_PORT,
    MAIL_USE_TLS=MAIL_USE_TLS,
    MAIL_USE_SSL=MAIL_USE_SSL,
    MAIL_USERNAME=MAIL_USERNAME,
    MAIL_PASSWORD=MAIL_PASSWORD,
))
app.config.from_envvar('GAMES_SETTINGS', silent=True)

mail = Mail(app)

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
    added_by = Column(String, ForeignKey('users.id'))

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    role = Column(String)
    email = Column(String, unique=True)
    oauth_token = Column(String)
    notify = Column(Integer)
    events = relationship('Event', backref='player')

class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    email_changes = Column(Integer, nullable=False)
    added_by = Column(String, ForeignKey('users.id'))
    added_self = Column(Integer)

def init_db():
    Base.metadata.create_all(bind=engine)

# Create classes for WTForms

class NewEvent(Form):
    date = DateField('date', [validators.Required()])
    time = TextField('time', [validators.Required()])
    location = TextField('location', [validators.Required()])
    title = TextField('title', [validators.Optional()])
    description = TextAreaField('description', [validators.Optional()])
    minimum = TextField('minimum', [validators.Optional()])
    maximum = TextField('maximum', [validators.Optional()])

class AddGuest(Form):
    name = TextField('name', [validators.Optional()])
    email_changes = BooleanField('email_changes', [validators.Optional()])
    event_id = HiddenField('event_id', [validators.Required()])

class RemovePlayer(Form):
    id = HiddenField('id')

class EditEvent(Form):
    id = HiddenField('id')
    date = DateField('date', [validators.Required()])
    time = TextField('time', [validators.Required()])
    location = TextField('location', [validators.Required()])
    title = TextField('title', [validators.Optional()])
    description = TextAreaField('description', [validators.Optional()])
    minimum = TextField('minimum', [validators.Optional()])
    maximum = TextField('maximum', [validators.Optional()])

class EditUser(Form):
    name = TextField('name')
    email = TextField('email')
    notify = BooleanField('notify', [validators.Optional()])

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
    events = sorted(events, key=lambda x: datetime.strptime(x.date, '%B %d, %Y'), reverse=False)
    players = {}
    adders = {}
    for player in Player.query.all():
        try:
            players[player.event_id].append(player)
        except KeyError:
            players[player.event_id] = []
            players[player.event_id].append(player)
        if player.added_self==1:
            try:
                adders[player.event_id].append(player.added_by)
            except KeyError:
                adders[player.event_id] = []
                adders[player.event_id].append(player.added_by)
    names = {}
    for u in User.query.all():
        names[u.id] = u.name
    new_event = NewEvent(request.form)
    add_guest = AddGuest(request.form)
    remove_player = RemovePlayer(request.form)
    edit_event = EditEvent(request.form)
    return render_template('index.html', user=user, events=events, players=players, adders=adders, names=names, new_event=new_event, \
                            add_guest=add_guest, remove_player=remove_player, edit_event=edit_event)

@app.route('/add_event', methods=['POST'])
def add_event():
    new_event = NewEvent(request.form)
    user = session.get('user')
    user = User.query.filter(User.id == user).first()
    if new_event.validate_on_submit():
        event = Event(date=new_event.date.data, time=new_event.time.data, location=new_event.location.data, \
                host=user.name, title=new_event.title.data, description=new_event.description.data, \
                minimum=new_event.minimum.data, maximum=new_event.maximum.data, added_by=user.id)
        db_session.add(event)
        db_session.commit()
        db_session.flush()
        flash('New event was successfully created')
        users = User.query.all()
        date = datetime.strftime(datetime.strptime(event.date, '%Y-%m-%d'), '%B %d, %Y')
        for u in users:
            if u.notify == 1:
                msg = Message("New gametimes!",
                        sender="Gamebot",
                        recipients=[u.email],
                        body="There's a new game event!\n\n"+date+" at "+event.time+"\n\nIt's hosted by "+event.host+" at "+event.location+"\n\nAbout it: "+event.description+"\n\nGo to www.stvnrlly.com/games to check it out.")
                mail.send(msg)
    else:
        flash(new_event.errors)
    return redirect('/games')

@app.route('/add_guest', methods=['POST'])
def add_guest():
    add_guest = AddGuest(request.form)
    user = session.get('user')
    user = User.query.filter(User.id == user).first()
    if add_guest.validate_on_submit():
        try:
            if request.form['btn'] == 'self':
                player = Player(email_changes=add_guest.email_changes.data, event_id=add_guest.event_id.data, name=user.name, added_by=user.id, added_self=True)
            if request.form['btn'] == 'other':
                player = Player(name=add_guest.name.data, event_id=add_guest.event_id.data, email_changes=False, added_by=user.id, added_self=False)
            db_session.add(player)
            db_session.commit()
            db_session.flush()
            event = Event.query.filter(Event.id == add_guest.event_id.data).first()
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
            notify = User.query.filter(User.id == event.added_by).first()
            date = datetime.strftime(datetime.strptime(event.date, '%Y-%m-%d'), '%B %d, %Y')
            msg = Message("You have a new guest!",
                    sender="Gamebot",
                    recipients=[notify.email],
                    body=player.name+" is coming to "+event.title+" on "+date+"!")
            mail.send(msg)
        except exc.SQLAlchemyError:
            flash("You've already added that person! Try another name.")
    else:
        flash(add_guest.errors)
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

# Profile page where user can see and edit user info

@app.route('/profile', methods=['GET'])
def profile():
    edit_user = EditUser(request.form)
    user = session.get('user')
    user = User.query.filter(User.id == user).first()
    if user:
        profile_events = {}
        for player in Player.query.all():
            if player.added_by == str(user.id) and player.added_self == 1:
                e = Event.query.filter(Event.id == player.event_id).first()
                e.date = datetime.strftime(datetime.strptime(e.date, '%Y-%m-%d'), '%B %d, %Y')
                profile_events[e] = 'guest'
        for event in Event.query.all():
            if event.added_by == str(user.id):
                e = Event.query.filter(Event.id == event.id).first()
                e.date = datetime.strftime(datetime.strptime(e.date, '%Y-%m-%d'), '%B %d, %Y')
                profile_events[e] = 'host'
        events = Event.query.all()
        return render_template('profile.html', user=user, edit_user=edit_user, profile_events=profile_events, events=events)
    else:
        return redirect('/games')

@app.route('/edit_user', methods=['GET', 'POST'])
def edit_user():
    edit_user = EditUser(request.form)
    user = session.get('user')
    user = User.query.filter(User.id == user).first()
    if edit_user.validate_on_submit():
        user.name = edit_user.name.data
        user.email = edit_user.email.data
        user.notify = edit_user.notify.data
        db_session.commit()
        db_session.flush()
    else:
        flash(edit_event.errors)
    return redirect('/profile')

# Handle login using OAuth

@app.route('/login')
def login():
    callback=url_for('authorized', _external=True)
    return google.authorize(callback=callback)
    # To set callback URL directly, set CALLBACK in creds.py
    # and comment out above code
    #
    # return google.authorize(CALLBACK)

@app.route('/logout')
def logout():
    session.pop('user')
    return redirect('/games')

@app.route('/oauth2callback')
@google.authorized_handler
def authorized(resp):
    access_token = resp['access_token']
    headers = {'Authorization': 'OAuth '+access_token}
    req = Request('https://www.googleapis.com/oauth2/v1/userinfo',
                  None, headers)
    try:
        res = urlopen(req)
    except URLError, e:
        if e.code == 401:
            # Unauthorized - bad token
            session.pop('access_token', None)
            return redirect('/login')
        user = res.read()
    info = json.loads(res.read())
    user = User.query.filter(User.oauth_token == info['id']).first()
    if user == None:
        user = User(name = info['name'], email = info['email'], oauth_token = info['id'], role='user', notify=0)
        db_session.add(user)
        db_session.commit()
        db_session.flush()
    session['user'] = user.id
    return redirect('/games')

@google.tokengetter
def get_access_token():
    return session.get('access_token')

# Error pages

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def something_wrong(e):
    return render_template('500.html'), 500

# Run the application

if __name__ == '__main__':
    init_db()
    app.run()
