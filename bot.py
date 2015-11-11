#!/usr/bin/env python3
"""Bot that replies to any @mention with Taylor Swift lyrics."""

from twitter import Twitter, TwitterStream, OAuth
from pprint import pformat
from abc import ABCMeta
import random
import logging

# API_KEY, API_SECRET, ACCESS_TOKEN, and ACCESS_TOKEN_SECRET come from here!
import secrets


log = logging.getLogger('PySwizzle')


class BotInterface(object):
    """
    This is an abstract base class representing a bot's interface to a service.

    It's nice to test the bot on a list of prepared tweets/updates from Twitter.
    So, it's useful to abstract the interface of the bot to the outside world
    into its own class.  This allows you to plug the bot into a new interface as
    simply as adding a new implementation of this class.
    """
    __metaclass__ = ABCMeta

    def __iter__(self):
        """
        Should return an iterator yielding Tweet dicts.
        """
        pass

    def tweet(self, msg, reply_to=None):
        """
        Send a tweet with message "msg", optionally in reply to a previous one.
        """
        pass


class TwitterInterface(BotInterface):
    """
    Production interface from the bot to the Twitter API.
    """

    def __init__(self, access_token=secrets.ACCESS_TOKEN,
                 access_token_secret=secrets.ACCESS_TOKEN_SECRET,
                 api_key=secrets.API_KEY,
                 api_secret=secrets.API_SECRET):

        self.auth = OAuth(access_token, access_token_secret, api_key,
                          api_secret)
        self.open_stream()

    def open_stream(self):
        """
        Opens an interface to the Twitter API and opens a stream.
        """
        t = Twitter(auth=self.auth)
        ts = TwitterStream(domain='userstream.twitter.com', auth=self.auth)

        self.twitter = t
        self.stream = ts.user()
        self.iterator = iter(self.stream)

    def __iter__(self):
        """
        This class is its own iterator!
        """
        return self

    def __next__(self):
        """
        This always yields tweets, and never listens to Twitter's hangups!
        """
        n = next(self.iterator)
        if 'hangup' in n:
            self.open_stream()
            return next(self)
        else:
            return n

    def tweet(self, msg, reply_to=None):
        """
        Send a tweet via the twitter API.
        """
        if reply_to is None:
            self.twitter.statuses.update(status=msg)
        else:
            self.twitter.statuses.update(status=msg,
                                         in_reply_to_status_id=reply_to)


class DebugInterface(object):
    """
    Useful for debugging!

    This interface allows you to provide a list of tweets that will be given to
    the bot, and any bot Tweet output will be printed right out.
    """

    def __init__(self, tweets):
        self.tweets = tweets

    def __iter__(self):
        return iter(self.tweets)

    def tweet(self, msg, **kwargs):
        log.info('SEND: "%s"' % msg)


class PySwizzle(object):
    """
    A class that represents the PySwizzle bot!

    This class handles PySwizzle's main duties: receiving input tweets and
    producing output based on lyrics (or, in the future, based on commands that
    I send it).
    """

    def __init__(self, interface, username='pyswizzle'):
        """
        Create a PySwizzle.  You must provide an interface.
        """
        self.interface = interface
        self.username = username
        # Events are generated by twitter - Follow, Profile update, like, etc.
        # The bot may want to respond to them, so this dictionary can hold
        # callbacks for different event types.
        self.events = {}
        # Commands are a feature I am intending to add.  I will be able to send
        # PySwizzle commands to do things like reload lyrics, or something.
        self.commands = {}
        self.lyrics = None
        self.lyrics_lower = None

    def load_lyrics(self, filename='taylor.txt'):
        # open up a file and get a list of lines of lyrics (no blank lines)
        with open(filename) as lyrics_file:
            self.lyrics = [l.strip() for l in lyrics_file if l != "\n"]
            self.lyrics_lower = [l.lower() for l in self.lyrics]

    def similarity(self, pieces, line):
        """
        Return a similarity score for a set of words from a tweet.

        This is a very rough similarity score that counts the number of words
        from the tweet that occur in the lyric.  It doesn't account for the fact
        that many of the words just be contained in another word in the lyric
        (eg, "in" is in "contained").  So there is room for improvement, but
        this is an interesting twist.
        """
        return sum(piece in line for piece in pieces)

    def choose_lyric(self, text):
        """
        Given a tweet's text, select and return a lyric.

        This randomly selects a lyric from the list of lyrics that have maximum
        similarity with the tweet.  See above for a definition of similarity.
        """
        pieces = set(text.lower().split())
        scores = [self.similarity(pieces, line) for line in self.lyrics_lower]
        max_score = max(scores)
        log.info('MAX SCORE: %d' % max_score)
        lines = [self.lyrics[i] for i, score in enumerate(scores)
                 if score == max_score]
        return random.choice(lines)

    def handle_tweet(self, tweet):
        """
        Called whenever an actual "tweet" (as opposed to an event) comes in.
        """
        # Ignore tweets that we sent.
        if tweet['user']['screen_name'] == self.username:
            return

        # Ignore tweets that we aren't @mentioned in.
        mentions = tweet['entities']['user_mentions']
        mentions.append(tweet['user'])
        usernames = set(m['screen_name'] for m in mentions)
        if self.username not in usernames:
            log.info('NOT IN THAT TWEET')
            return

        # We want to make sure we prefix our reply with the usernames of
        # everyone involved with the conversation.
        usernames = ['@' + u for u in usernames if u != self.username]
        line = self.choose_lyric(tweet['text'])
        reply = ' '.join(usernames) + ' ' + line
        if len(reply) > 140:
            log.warning('ALMOST SENT TOO LONG REPLY "%s"' % reply)
            reply = reply[:140]
        self.interface.tweet(reply, reply_to=tweet['id'])

    def run(self):
        """
        Run the bot indefinitely.
        """
        if self.lyrics is None:
            self.load_lyrics()

        for tweet in self.interface:
            log.debug('TWEET:' + pformat(tweet))

            if 'event' in tweet:
                if tweet['event'] in self.events:
                    log.info('HANDLING EVENT "%s".' % tweet['event'])
                    self.events[tweet['event']](tweet)
                else:
                    log.info('UNHANDLED EVENT "%s".' % tweet['event'])

            elif 'text' in tweet:
                log.info('HANDLING TWEET: @%s: \"%s\"' %
                         (tweet['user']['screen_name'], tweet['text']))
                self.handle_tweet(tweet)


def main():
    from argparse import ArgumentParser, FileType
    import sys
    parser = ArgumentParser(description='Run pyswizzle bot.')

    parser.add_argument('--local', type=FileType('r'), default=None,
                        help='use a script of tweets instead of going live')
    parser.add_argument('--log-file', type=FileType('w'), default=sys.stdout,
                        help='file to log to (stdout by default)')
    parser.add_argument('--level', type=str, default='INFO',
                        help='log level for output')

    args = parser.parse_args()

    log.addHandler(logging.StreamHandler(args.log_file))
    log.setLevel(logging.getLevelName(args.level))

    if args.local is not None:
        # don't be stupid please
        tweets = eval(args.local.read())
        interface = DebugInterface(tweets)
    else:
        interface = TwitterInterface()
    bot = PySwizzle(interface)
    bot.run()

if __name__ == '__main__':
    main()
