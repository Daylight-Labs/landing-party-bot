from enum import Enum, unique
from database import execute_sql

class CommunityConfiguration:

    def __init__(
        self,
        internal_id: int,
        display_name: str,
        guild_id: str,
        guild_slug: str,
        users_with_write_access: [int],
        active_channels: [int],
        is_active: bool,
        minimum_threshold: float,
        admin_role_ids: [int],
        verified_role_id,
        kick_users_who_joined_but_did_not_verify_after_days,
        kick_users_who_joined_but_did_not_verify_after_hours,
        kick_users_ignore_datetime_before_utc,
        kick_users_who_sent_spam_times
    ):
        self.internal_id = internal_id
        self.display_name = display_name
        self.guild_id = guild_id
        self.guild_slug = guild_slug
        self.users_with_write_access = users_with_write_access
        self.active_channels = active_channels
        self.is_active = is_active
        self.minimum_threshold = minimum_threshold
        self.admin_role_ids = admin_role_ids
        self.verified_role_id = verified_role_id
        self.kick_users_who_joined_but_did_not_verify_after_days = kick_users_who_joined_but_did_not_verify_after_days
        self.kick_users_who_joined_but_did_not_verify_after_hours = kick_users_who_joined_but_did_not_verify_after_hours
        self.kick_users_ignore_datetime_before_utc = kick_users_ignore_datetime_before_utc
        self.kick_users_who_sent_spam_times = kick_users_who_sent_spam_times

    def __eq__(self, other):
        return self.guild_id == other.guild_id

    def has_admin_role(self, user):
        for role in user.roles:
            if role.id in self.admin_role_ids:
                return role.id
        return False

    def user_has_admin_access(self, user):
        try:
            if user.id in self.users_with_write_access:
                return True

            for role in user.roles:
                if role.id in self.admin_role_ids:
                    return True

            return False
        except:
            return False

SUPPORTED_COMMUNITIES = {}

def initialize_all_supported_communities():
    # TODO: Make Async
    for k in list(SUPPORTED_COMMUNITIES.keys()):
        del SUPPORTED_COMMUNITIES[k]

    q = execute_sql("""
        SELECT c.id, 
           c.id AS internal_id,
           c.name AS name,
           c.slug AS slug,
           c.guild_id AS guild_id,
           string_agg(DISTINCT u.discord_user_id :: text, ',') AS community_admin_ids,
           string_agg(DISTINCT adc.channel_id :: text, ',') AS discord_channel_ids,
           c.is_active AS is_active,
           c.minimum_threshold AS minimum_threshold,
           admin_role_ids,
           verified_role_id,
           kick_users_who_joined_but_did_not_verify_after_days,
           kick_users_who_joined_but_did_not_verify_after_hours,
           kick_users_ignore_datetime_before_utc,
           kick_users_who_sent_spam_times
        FROM api_community c 
        LEFT JOIN api_community_admins ca ON c.id = ca.community_id
        LEFT JOIN api_user u ON ca.user_id = u.id
        LEFT JOIN api_botenableddiscordchannel dc ON c.id = dc.community_id AND dc.deleted_on IS NULL
        LEFT JOIN api_alldiscordchanels adc on dc.channel_ref_id = adc.id
        GROUP BY c.id
    """)

    def split_nums(str):
        return list(map(int, filter(lambda x: bool(x), (str or '').split(','))))

    for row in q:
        internal_id = row['internal_id']
        name = row['name']
        slug = row['slug']
        guild_id = row['guild_id']
        community_admin_ids = split_nums(row['community_admin_ids'])
        discord_channel_ids = split_nums(row['discord_channel_ids'])
        is_active = row['is_active']
        minimum_threshold = row['minimum_threshold']
        admin_role_ids = split_nums(row['admin_role_ids'])
        verified_role_id = row['verified_role_id']
        kick_users_who_joined_but_did_not_verify_after_days = row['kick_users_who_joined_but_did_not_verify_after_days']
        kick_users_who_joined_but_did_not_verify_after_hours = row['kick_users_who_joined_but_did_not_verify_after_hours']
        kick_users_ignore_datetime_before_utc = row['kick_users_ignore_datetime_before_utc']
        kick_users_who_sent_spam_times = row['kick_users_who_sent_spam_times']
        SUPPORTED_COMMUNITIES[guild_id] = CommunityConfiguration(
            internal_id=internal_id,
            display_name=name,
            guild_id=guild_id,
            guild_slug=slug,
            users_with_write_access=community_admin_ids,
            active_channels=discord_channel_ids,
            is_active=is_active,
            minimum_threshold=minimum_threshold,
            admin_role_ids=admin_role_ids,
            verified_role_id=verified_role_id,
            kick_users_who_joined_but_did_not_verify_after_days=kick_users_who_joined_but_did_not_verify_after_days,
            kick_users_who_joined_but_did_not_verify_after_hours=kick_users_who_joined_but_did_not_verify_after_hours,
            kick_users_ignore_datetime_before_utc=kick_users_ignore_datetime_before_utc,
            kick_users_who_sent_spam_times=kick_users_who_sent_spam_times
        )
