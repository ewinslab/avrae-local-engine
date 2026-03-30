"""
Mock disnake module — allows avrae's source code to run without Discord.
Inject this BEFORE any avrae imports via: import mock_disnake
"""

import sys
from typing import Any


# ============================================================
# Core mock classes
# ============================================================

class MockEmbed:
    def __init__(self, title=None, description=None, color=None, colour=None, **kwargs):
        self.title = title
        self.description = description
        self.color = color or colour
        self.fields = []
        self.footer = None
        self.image = None
        self.thumbnail = None
        self.author_info = None
        self.__dict__.update(kwargs)

    def add_field(self, name="", value="", inline=False):
        self.fields.append({"name": name, "value": value, "inline": inline})
        return self

    def set_field_at(self, index, name="", value="", inline=False):
        if 0 <= index < len(self.fields):
            self.fields[index] = {"name": name, "value": value, "inline": inline}
        return self

    def insert_field_at(self, index, name="", value="", inline=False):
        self.fields.insert(index, {"name": name, "value": value, "inline": inline})
        return self

    def clear_fields(self):
        self.fields = []
        return self

    def set_footer(self, text="", icon_url=None):
        self.footer = {"text": text, "icon_url": icon_url}
        return self

    def set_image(self, url=None):
        self.image = url
        return self

    def set_thumbnail(self, url=None):
        self.thumbnail = url
        return self

    def set_author(self, name="", url=None, icon_url=None):
        self.author_info = {"name": name, "url": url, "icon_url": icon_url}
        return self

    def to_dict(self):
        return {"title": self.title, "description": self.description,
                "fields": self.fields}

    def copy(self):
        e = MockEmbed(title=self.title, description=self.description, color=self.color)
        e.fields = list(self.fields)
        e.footer = self.footer
        return e


class MockUser:
    def __init__(self, id=0, name="MockUser", discriminator="0000"):
        self.id = int(id)
        self.name = name
        self.discriminator = discriminator
        self.display_name = name
        self.mention = f"<@{id}>"
        self.bot = False
        self.avatar = None

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, MockUser) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


class MockMember(MockUser):
    def __init__(self, id=0, name="MockMember", **kwargs):
        super().__init__(id, name)
        self.guild = kwargs.get("guild")
        self.roles = []
        self.nick = None

    async def send(self, content=None, **kwargs):
        return MockMessage(content=content)


class MockChannel:
    def __init__(self, id=0, name="mock-channel"):
        self.id = int(id)
        self.name = name
        self.mention = f"<#{id}>"
        self.guild = None

    async def send(self, content=None, **kwargs):
        return MockMessage(content=content)

    def __str__(self):
        return self.name


class MockTextChannel(MockChannel):
    pass


class MockThread(MockChannel):
    pass


class MockGuild:
    def __init__(self, id=0, name="MockGuild"):
        self.id = int(id)
        self.name = name
        self.members = []
        self.me = MockMember(id=999, name="Bot")

    async def fetch_member(self, member_id):
        return MockMember(id=member_id)

    def get_member(self, member_id):
        return MockMember(id=member_id)


class MockMessage:
    def __init__(self, id=0, content=None, **kwargs):
        self.id = int(id)
        self.content = content
        self.author = MockUser()
        self.channel = MockChannel()
        self.guild = MockGuild()

    async def edit(self, **kwargs):
        pass

    async def delete(self):
        pass

    async def add_reaction(self, emoji):
        pass


class MockPartialMessage:
    def __init__(self, channel=None, id=0):
        self.channel = channel
        self.id = id

    async def edit(self, **kwargs):
        pass


class MockAllowedMentions:
    def __init__(self, everyone=False, users=None, roles=None, replied_user=True):
        self.everyone = everyone
        self.users = users or []
        self.roles = roles or []
        self.replied_user = replied_user

    @classmethod
    def none(cls):
        return cls()

    @classmethod
    def all(cls):
        return cls(everyone=True)

    def merge(self, other):
        return self


class MockObject:
    def __init__(self, id=0):
        self.id = id


class MockColour:
    def __init__(self, value=0):
        self.value = value

    @classmethod
    def random(cls):
        return cls(0x000000)

    @classmethod
    def default(cls):
        return cls(0)

    def __int__(self):
        return self.value


MockColor = MockColour


class MockHTTPException(Exception):
    pass


class MockForbidden(MockHTTPException):
    pass


class MockNotFound(MockHTTPException):
    pass


class MockInteraction:
    def __init__(self):
        self.author = MockUser()
        self.user = MockUser()
        self.channel = MockChannel()
        self.channel_id = 0
        self.guild = MockGuild()
        self.guild_id = 0
        self.response = self
        self.id = 0

    async def send_message(self, content=None, **kwargs):
        pass

    async def defer(self, **kwargs):
        pass

    async def edit_original_message(self, **kwargs):
        pass


class MockApplicationCommandInteraction(MockInteraction):
    pass


class MockMessageInteraction(MockInteraction):
    pass


# ============================================================
# Mock UI module
# ============================================================

class MockButton:
    def __init__(self, label=None, style=None, custom_id=None, **kwargs):
        self.label = label
        self.style = style
        self.custom_id = custom_id


class MockSelect:
    def __init__(self, **kwargs):
        pass


class MockView:
    def __init__(self, **kwargs):
        self.children = []

    def add_item(self, item):
        self.children.append(item)

    async def wait(self):
        pass


class MockActionRow:
    def __init__(self, *args):
        self.children = list(args)


class MockButtonStyle:
    primary = 1
    secondary = 2
    success = 3
    danger = 4
    link = 5
    blurple = 1
    grey = 2
    gray = 2
    green = 3
    red = 4


class MockUI:
    Button = MockButton
    Select = MockSelect
    View = MockView
    ActionRow = MockActionRow
    button = lambda **kwargs: lambda f: f
    select = lambda **kwargs: lambda f: f
    string_select = lambda **kwargs: lambda f: f


# ============================================================
# Mock ext.commands module
# ============================================================

class MockCog:
    __cog_name__ = "MockCog"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __init__(self, bot=None):
        self.bot = bot

    @classmethod
    def listener(cls, name=None):
        def decorator(func):
            return func
        return decorator


class MockContext:
    def __init__(self):
        self.author = MockUser()
        self.channel = MockChannel()
        self.guild = MockGuild()
        self.bot = None
        self.message = MockMessage()
        self.prefix = "!"
        self.invoked_with = ""

    async def send(self, content=None, **kwargs):
        return MockMessage(content=content)

    async def trigger_typing(self):
        pass


class MockBot:
    def __init__(self):
        self.user = MockUser(id=999, name="Bot")

    def get_cog(self, name):
        return None

    def get_channel(self, channel_id):
        return MockChannel(id=channel_id)


class MockCommandError(Exception):
    pass


class MockCheckFailure(MockCommandError):
    pass


class MockNoPrivateMessage(MockCheckFailure):
    pass


class MockBadArgument(MockCommandError):
    pass


class MockUserInputError(MockCommandError):
    pass


class MockArgumentParsingError(MockCommandError):
    pass


class MockExpectedClosingQuoteError(MockCommandError):
    pass


class MockCommandInvokeError(MockCommandError):
    def __init__(self, original=None):
        self.original = original
        super().__init__(str(original) if original else "")


class MockDiscordException(Exception):
    pass


class MockBucketType:
    default = 0
    user = 1
    guild = 2
    channel = 3
    member = 4
    category = 5
    role = 6


class MockGroup:
    def __init__(self, *args, **kwargs):
        pass
    def command(self, **kwargs):
        def decorator(func):
            func.__command_attrs__ = kwargs
            return func
        return decorator
    def group(self, **kwargs):
        def decorator(func):
            func.__command_attrs__ = kwargs
            return func
        return decorator


class MockHelpCommand:
    def __init__(self, **kwargs):
        pass


class MockStringView:
    """Full StringView implementation matching disnake.ext.commands.view.StringView exactly."""
    def __init__(self, buffer=""):
        self.index = 0
        self.buffer = buffer
        self.end = len(buffer)
        self.previous = 0

    @property
    def current(self):
        return None if self.eof else self.buffer[self.index]

    @property
    def eof(self):
        return self.index >= self.end

    def undo(self):
        self.index = self.previous

    def skip_ws(self):
        pos = 0
        while not self.eof:
            try:
                current = self.buffer[self.index + pos]
                if not current.isspace():
                    break
                pos += 1
            except IndexError:
                break
        self.previous = self.index
        self.index += pos
        return self.previous != self.index

    def skip_string(self, string):
        strlen = len(string)
        if self.buffer[self.index:self.index + strlen] == string:
            self.previous = self.index
            self.index += strlen
            return True
        return False

    def read_rest(self):
        result = self.buffer[self.index:]
        self.previous = self.index
        self.index = self.end
        return result

    def read(self, n):
        result = self.buffer[self.index:self.index + n]
        self.previous = self.index
        self.index += n
        return result

    def get(self):
        try:
            result = self.buffer[self.index + 1]
        except IndexError:
            result = None
        self.previous = self.index
        self.index += 1
        return result

    def get_word(self):
        pos = 0
        while not self.eof:
            try:
                current = self.buffer[self.index + pos]
                if current.isspace():
                    break
                pos += 1
            except IndexError:
                break
        self.previous = self.index
        result = self.buffer[self.index:self.index + pos]
        self.index += pos
        return result

    def get_quoted_word(self):
        current = self.current
        if current is None:
            return None
        result = [current]
        while not self.eof:
            current = self.get()
            if not current:
                return "".join(result)
            if current.isspace():
                return "".join(result)
            result.append(current)

    def __repr__(self):
        return f"<StringView pos: {self.index} prev: {self.previous} end: {self.end} eof: {self.eof}>"


class MockCommandSyncFlags:
    @classmethod
    def default(cls):
        return cls()


class MockHTTPClient:
    pass


class MockRoute:
    def __init__(self, *args, **kwargs):
        pass


class _MockCommand:
    """A mock command that supports .command() and .group() sub-decorators."""
    def __init__(self, func=None, **kwargs):
        self._func = func
        self.__name__ = func.__name__ if func else "mock"
        self.__doc__ = func.__doc__ if func else ""
        # Make it callable like the original function
        if func:
            self.__wrapped__ = func

    def __call__(self, *args, **kwargs):
        if self._func:
            return self._func(*args, **kwargs)

    def command(self, *args, **kwargs):
        def decorator(func):
            cmd = _MockCommand(func, **kwargs)
            return cmd
        return decorator

    def group(self, *args, **kwargs):
        def decorator(func):
            cmd = _MockCommand(func, **kwargs)
            return cmd
        return decorator

    def __get__(self, obj, objtype=None):
        # Support as a descriptor (method binding)
        if obj is None:
            return self
        return self


def _noop_decorator(**kwargs):
    def decorator(func):
        return _MockCommand(func, **kwargs)
    return decorator


class MockCommands:
    Cog = MockCog
    Context = MockContext
    Bot = MockBot
    AutoShardedBot = MockBot
    CommandError = MockCommandError
    CheckFailure = MockCheckFailure
    NoPrivateMessage = MockNoPrivateMessage
    BadArgument = MockBadArgument
    UserInputError = MockUserInputError
    ArgumentParsingError = MockArgumentParsingError
    ExpectedClosingQuoteError = MockExpectedClosingQuoteError
    CommandInvokeError = MockCommandInvokeError
    BucketType = MockBucketType
    Group = MockGroup
    HelpCommand = MockHelpCommand
    StringView = MockStringView
    CommandSyncFlags = MockCommandSyncFlags

    command = staticmethod(_noop_decorator)
    group = staticmethod(_noop_decorator)
    check = staticmethod(lambda f: lambda func: func)
    guild_only = staticmethod(lambda: lambda func: func)
    is_owner = staticmethod(lambda: lambda func: func)
    cooldown = staticmethod(lambda *a, **kw: lambda func: func)
    max_concurrency = staticmethod(lambda *a, **kw: lambda func: func)
    has_guild_permissions = staticmethod(lambda **kw: lambda func: func)
    has_permissions = staticmethod(lambda **kw: lambda func: func)
    bot_has_permissions = staticmethod(lambda **kw: lambda func: func)
    bot_has_guild_permissions = staticmethod(lambda **kw: lambda func: func)
    dm_only = staticmethod(lambda: lambda func: func)
    Greedy = list
    Range = int
    Param = lambda **kw: kw.get("default")

    @staticmethod
    def slash_command(**kwargs):
        return _noop_decorator(**kwargs)

    @staticmethod
    def message_command(**kwargs):
        return _noop_decorator(**kwargs)


class MockExt:
    commands = MockCommands


# ============================================================
# Mock utils module
# ============================================================

class MockUtils:
    @staticmethod
    def escape_markdown(text, as_needed=True):
        return str(text) if text else ""

    @staticmethod
    def escape_mentions(text):
        return str(text) if text else ""

    @staticmethod
    def utcnow():
        import datetime
        return datetime.datetime.utcnow()

    @staticmethod
    def format_dt(dt, style="f"):
        return str(dt)


# ============================================================
# Mock errors module
# ============================================================

class MockErrors:
    Forbidden = MockForbidden
    HTTPException = MockHTTPException
    NotFound = MockNotFound
    DiscordException = MockDiscordException


class MockHttp:
    HTTPClient = MockHTTPClient
    Route = MockRoute


# ============================================================
# Top-level mock disnake module
# ============================================================

class MockDisnake:
    # Classes
    Embed = MockEmbed
    User = MockUser
    Member = MockMember
    TextChannel = MockTextChannel
    Thread = MockThread
    Guild = MockGuild
    Message = MockMessage
    PartialMessage = MockPartialMessage
    AllowedMentions = MockAllowedMentions
    Object = MockObject
    Colour = MockColour
    Color = MockColor
    Interaction = MockInteraction
    ApplicationCommandInteraction = MockApplicationCommandInteraction
    MessageInteraction = MockMessageInteraction
    Intents = type('Intents', (), {'all': classmethod(lambda cls: cls()),
                                    'default': classmethod(lambda cls: cls()),
                                    '__init__': lambda self, **kw: None})
    HTTPException = MockHTTPException
    Forbidden = MockForbidden
    NotFound = MockNotFound
    DiscordException = MockDiscordException

    # Sub-modules
    ext = MockExt
    ui = MockUI
    utils = MockUtils
    errors = MockErrors

    # Components
    Component = type('Component', (), {})
    Button = MockButton
    SelectOption = type('SelectOption', (), {'__init__': lambda self, **kw: None})
    ActionRow = MockActionRow
    MessageFlags = type('MessageFlags', (), {'ephemeral': 64})

    # Enums
    ButtonStyle = MockButtonStyle

    # ABC
    class abc:
        class Messageable:
            async def send(self, content=None, **kwargs):
                return MockMessage(content=content)
        class GuildChannel:
            pass
        class PrivateChannel:
            pass
        class Connectable:
            pass

    # Functions
    Game = lambda name: type('Game', (), {'name': name})()
    Activity = lambda **kw: None


# ============================================================
# Install into sys.modules
# ============================================================

_mock = MockDisnake()

# Sub-modules for disnake.ext.commands (needs to look like a package)
class MockCommandsView:
    StringView = MockStringView

class MockCommandsCooldowns:
    BucketType = MockBucketType

class MockCommandsErrors:
    CommandError = MockCommandError
    CheckFailure = MockCheckFailure
    NoPrivateMessage = MockNoPrivateMessage
    BadArgument = MockBadArgument
    UserInputError = MockUserInputError
    ArgumentParsingError = MockArgumentParsingError
    ExpectedClosingQuoteError = MockExpectedClosingQuoteError
    CommandInvokeError = MockCommandInvokeError
    NotOwner = type('NotOwner', (MockCheckFailure,), {})

class MockCommandsCommand:
    pass

class MockCommandsContext:
    pass

sys.modules['disnake'] = _mock
sys.modules['disnake.ext'] = MockExt
sys.modules['disnake.ext.commands'] = MockCommands
sys.modules['disnake.ext.commands.view'] = MockCommandsView
sys.modules['disnake.ext.commands.cooldowns'] = MockCommandsCooldowns
sys.modules['disnake.ext.commands.errors'] = MockCommandsErrors
sys.modules['disnake.ext.commands.Command'] = MockCommandsCommand
sys.modules['disnake.ext.commands.Context'] = MockCommandsContext
sys.modules['disnake.ui'] = MockUI
sys.modules['disnake.utils'] = MockUtils
sys.modules['disnake.errors'] = MockErrors
sys.modules['disnake.http'] = MockHttp
sys.modules['disnake.abc'] = MockDisnake.abc
