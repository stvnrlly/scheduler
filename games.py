import os
from datetime import datetime
from sqlite3 import dbapi2 as sqlite3
from flask import Flask, request, session, g, redirect, url_for, abort, \
    render_template, flash
from flask.ext.wtf import Form
from flask_wtf.csrf import CsrfProtect
from wtforms import BooleanField, TextField, TextAreaField, PasswordField, \
    HiddenField, DateField, validators
from sqlalchemy import Column, Integer, String, ForeignKey, create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Create the application
csrf = CsrfProtect()
app = Flask(__name__)
csrf.init_app(app)

# Load default config and override config from an environment variable
app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'games.db'),
    DEBUG=True,
    SECRET_KEY='development key',
    USERNAME='admin',
    PASSWORD='default'
))
app.config.from_envvar('GAMES_SETTINGS', silent=True)

# Set up the database

engine = create_engine('sqlite:///games.db', convert_unicode=True)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    date = Column(String, nullable=False)
    time = Column(String, nullable=False)
    location = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(String)
    minimum = Column(Integer)
    maximum = Column(Integer)

    def __init__(self, date, time, location, title, description, minimum, maximum):
        self.date = date
        self.time = time
        self.location = location
        self.title = title
        self.description = description
        self.minimum = minimum
        self.maximum = maximum

class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    email = Column(String)

    def __init__(self, name, email, event_id):
        self.name = name
        self.email = email
        self.event_id = event_id

def init_db():
    Base.metadata.create_all(bind=engine)

# Create classes for WTForms

class NewEvent(Form):
    date = DateField('date', [validators.Required()], format='%m/%d/%Y')
    time = TextField('time', [validators.Required()])
    location = TextField('location', [validators.Required()])
    title = TextField('title', [validators.Optional()])
    description = TextAreaField('description', [validators.Optional()])
    minimum = TextField('minimum', [validators.Optional()])
    maximum = TextField('maximum', [validators.Optional()])

class NewPlayer(Form):
    name = TextField('name', [validators.Required()])
    email = HiddenField('email', [validators.Email(), validators.Optional()])
    event_id = HiddenField('event_id', [validators.Required()])

class RemovePlayer(Form):
    id = HiddenField('id')

# Make sure to close the database properly

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

# Create views

@app.route('/games', methods=['GET','POST'])
def games():
    events = []
    for event in Event.query.all():
        date = datetime.strptime(event.date, '%Y-%m-%d')
        if date > datetime.now():
            events.append(event)
    players = {}
    for player in Player.query.all():
        try:
            players[player.event_id].append(player)
        except KeyError:
            players[player.event_id] = []
            players[player.event_id].append(player)
    new_event = NewEvent(request.form)
    new_player = NewPlayer(request.form)
    remove_player = RemovePlayer(request.form)
    return render_template('games.html', events=events, players=players, new_event=new_event, \
                            new_player=new_player, remove_player=remove_player)

@app.route('/add_event', methods=['POST'])
def add_event():
    new_event = NewEvent(request.form)
    if new_event.validate_on_submit():
        event = Event(new_event.date.data, new_event.time.data, new_event.location.data, \
                new_event.title.data, new_event.description.data, new_event.minimum.data, new_event.maximum.data)
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
    if new_player.validate_on_submit():
        player = Player(new_player.name.data, new_player.email.data, new_player.event_id.data)
        db_session.add(player)
        db_session.commit()
        db_session.flush()
        flash('Success!')
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
        flash('Removed. Want to try another time?')
    else:
        flash(remove_player.errors)
    return redirect('/games')

# Run the application

if __name__ == '__main__':
    init_db()
    app.run()
