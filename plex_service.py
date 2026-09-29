from __future__ import annotations
import unicodedata
from typing import Optional, List, Dict, Any, Set
from plexapi.myplex import MyPlexAccount, MyPlexUser
from config import config
from logger_service import logger

def normalize_str(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(s))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).strip().lower()

def get_section_title(sec: Any) -> str:
    if isinstance(sec, str):
        return sec
    for attr in ("title", "name", "sectionName", "key"):
        val = getattr(sec, attr, None)
        if val and isinstance(val, str):
            return val
    return str(sec)

LIBRARY_ALIASES = {
    "movies": ["movies", "peliculas", "películas", "cine", "films", "pelicula"],
    "tv shows": ["tv shows", "tv", "shows", "series", "series de tv", "television", "tele"],
    "anime": ["anime", "animes"],
    "sports": ["sports", "deportes"]
}

def expand_target_libraries(target_libraries: List[str]) -> Set[str]:
    expanded: Set[str] = set()
    for lib in target_libraries:
        norm = normalize_str(lib)
        expanded.add(norm)
        if norm in LIBRARY_ALIASES:
            for alias in LIBRARY_ALIASES[norm]:
                expanded.add(normalize_str(alias))
        for key, aliases in LIBRARY_ALIASES.items():
            if norm in [normalize_str(a) for a in aliases]:
                expanded.add(normalize_str(key))
                for a in aliases:
                    expanded.add(normalize_str(a))
    return expanded

def is_section_in_targets(sec_title: str, target_libraries: List[str]) -> bool:
    """Checks if a Plex section title matches target libraries (exact, alias, substring, or token overlap)."""
    if not sec_title or not target_libraries:
        return False
    sec_norm = normalize_str(sec_title)
    if not sec_norm:
        return False
    target_libs_norm = expand_target_libraries(target_libraries)
    if sec_norm in target_libs_norm:
        return True
    for t_norm in target_libs_norm:
        if len(t_norm) >= 3 and (t_norm in sec_norm or sec_norm in t_norm):
            return True
    sec_tokens = set(sec_norm.split())
    for t_norm in target_libs_norm:
        t_tokens = set(t_norm.split())
        if t_tokens and t_tokens.issubset(sec_tokens):
            return True
    return False

def get_shared_server_id(account: MyPlexAccount, user_obj: Any, machine_id: str) -> Optional[int]:
    """Finds the shared server ID (serverId) for a user on a given server machine_id."""
    user_servers = getattr(user_obj, "servers", [])
    for s in user_servers:
        s_m_id = getattr(s, "machineIdentifier", None)
        if s_m_id and str(s_m_id).lower() == str(machine_id).lower():
            s_id = getattr(s, "id", None)
            if s_id:
                return s_id
    if user_servers and len(user_servers) == 1:
        s_id = getattr(user_servers[0], "id", None)
        if s_id:
            return s_id

    # Fallback: Query FRIENDINVITE endpoint for the machine_id directly
    try:
        if hasattr(account, "FRIENDINVITE") and hasattr(account, "query"):
            url = account.FRIENDINVITE.format(machineId=machine_id)
            elem = account.query(url)
            u_id = str(getattr(user_obj, "id", ""))
            u_email = normalize_str(getattr(user_obj, "email", ""))
            u_name = normalize_str(getattr(user_obj, "username", ""))
            u_title = normalize_str(getattr(user_obj, "title", ""))

            items = elem.findall(".//SharedServer") if hasattr(elem, "findall") else []
            if not items and hasattr(elem, "tag") and elem.tag == "SharedServer":
                items = [elem]
            
            for item in items:
                item_user_id = str(item.attrib.get("userID", ""))
                item_email = normalize_str(item.attrib.get("email", ""))
                item_username = normalize_str(item.attrib.get("username", ""))
                item_title = normalize_str(item.attrib.get("title", ""))
                share_id = item.attrib.get("id")

                if share_id:
                    if u_id and item_user_id == u_id:
                        return int(share_id)
                    if u_email and item_email == u_email:
                        return int(share_id)
                    if u_name and item_username == u_name:
                        return int(share_id)
                    if u_title and item_title == u_title:
                        return int(share_id)
    except Exception as e:
        logger.warning(f"Could not query FRIENDINVITE for machineId={machine_id}: {e}")

    return None

def update_friend_sections(
    account: MyPlexAccount,
    user: Any,
    server: Any,
    sections: Optional[List[Any]] = None,
    remove_sections: bool = False
) -> None:
    """
    Updates library section access for a friend on a server.
    Fixes a bug in plexapi.MyPlexAccount.updateFriend where setting empty sections ([])
    or removeSections=True for an existing friend silently fails without sending API requests.
    Sends DELETE request to FRIENDSERVERS so library access is removed while keeping friend status on Plex.
    """
    if isinstance(user, MyPlexUser) or hasattr(user, "servers") or hasattr(user, "email") or hasattr(user, "username"):
        user_obj = user
    else:
        user_obj = account.user(user)
    machine_id = server.machineIdentifier if hasattr(server, "machineIdentifier") else server
    headers = {'Content-Type': 'application/json'}

    server_id = get_shared_server_id(account, user_obj, machine_id)
    user_label = getattr(user_obj, 'email', getattr(user_obj, 'title', str(user_obj)))

    if remove_sections or not sections:
        # User keeps friend status, but section access for this server is set to [] (0 libraries)
        if server_id and hasattr(account, "FRIENDSERVERS") and hasattr(account, "query") and hasattr(account, "_session"):
            params = {'server_id': machine_id, 'shared_server': {'library_section_ids': []}}
            url_v1 = account.FRIENDSERVERS.format(machineId=machine_id, serverId=server_id)
            url_v2 = f"https://plex.tv/api/v2/shared_servers/{server_id}"
            
            logger.info(f"Revoking all library access for '{user_label}' by deleting shared server (serverId={server_id}, machineId={machine_id})...")
            
            success = False
            # Attempt 1: v2 DELETE (Modern API)
            try:
                account.query(url_v2, account._session.delete, json=params, headers=headers)
                logger.info(f"Successfully sent DELETE to {url_v2}")
                success = True
            except Exception as e1:
                logger.warning(f"DELETE to {url_v2} failed ({e1}). Trying v1 endpoint...")

            # Attempt 2: v1 DELETE (Legacy API)
            if not success:
                try:
                    account.query(url_v1, account._session.delete, json=params, headers=headers)
                    logger.info(f"Successfully sent DELETE to {url_v1}")
                    success = True
                except Exception as e3:
                    logger.error(f"All DELETE requests to remove shared server failed for '{user_label}': {e3}")
        else:
            logger.warning(f"Could not find shared server_id for '{user_label}' on machine {machine_id}. Falling back to updateFriend.")
        
        # Always invoke updateFriend for mock tracking/plexapi internal state if needed
        try:
            account.updateFriend(user=user_obj, server=server, removeSections=True)
        except Exception:
            pass
    else:
        # Non-empty sections list
        section_ids = account._getSectionIds(machine_id, sections) if hasattr(account, "_getSectionIds") else []
        params = {
            'server_id': machine_id, 
            'shared_server': {
                'library_section_ids': section_ids,
                'all_libraries': False
            }
        }
        if server_id and hasattr(account, "FRIENDSERVERS") and hasattr(account, "query") and hasattr(account, "_session"):
            url = account.FRIENDSERVERS.format(machineId=machine_id, serverId=server_id)
            logger.info(f"Sending PUT request to Plex serverId={server_id} with section_ids={section_ids} (all_libraries=0) for '{user_label}'...")
            try:
                account.query(url, account._session.put, json=params, headers=headers)
            except Exception as e:
                logger.warning(f"Direct PUT to FRIENDSERVERS failed ({e}), falling back to updateFriend.")
                account.updateFriend(user=user_obj, server=server, sections=sections)
        else:
            if hasattr(account, "FRIENDINVITE") and hasattr(user_obj, "id"):
                params['shared_server']['invited_id'] = user_obj.id
                url = account.FRIENDINVITE.format(machineId=machine_id)
                logger.info(f"Sending POST request to Plex FRIENDINVITE to recreate server access with section_ids={section_ids} (all_libraries=0) for '{user_label}'...")
                try:
                    account.query(url, account._session.post, json=params, headers=headers)
                except Exception as e:
                    logger.warning(f"Direct POST to FRIENDINVITE failed ({e}), falling back to updateFriend.")
                    account.updateFriend(user=user_obj, server=server, sections=sections)
            else:
                account.updateFriend(user=user_obj, server=server, sections=sections)

class PlexService:
    def __init__(self, cfg=config, account: Optional[MyPlexAccount] = None):
        self.cfg = cfg
        self._account = account

    def get_account(self) -> MyPlexAccount:
        if self._account is None:
            if not self.cfg.PLEX_TOKEN:
                raise ValueError("PLEX_TOKEN is missing in environment/config.")
            logger.info("Connecting to Plex Account via token...")
            self._account = MyPlexAccount(token=self.cfg.PLEX_TOKEN)
        return self._account

    def get_server(self):
        account = self.get_account()
        server_name = self.cfg.PLEX_SERVER_NAME
        
        if server_name:
            logger.info(f"Finding specified Plex server: '{server_name}'...")
            if hasattr(account, "server") and callable(getattr(account, "server")):
                try:
                    return account.server(server_name)
                except Exception:
                    pass
            return account.resource(server_name).connect()
        else:
            # If server name is not explicitly set, use the first owned server resource
            resources = [r for r in account.resources() if r.provides == "server" and r.owned]
            if not resources:
                raise RuntimeError("No owned Plex server resource found on account.")
            target_resource = resources[0]
            logger.info(f"Using default owned Plex server: '{target_resource.name}'...")
            return target_resource.connect()

    def find_user_by_email(self, email: str):
        """Finds a Plex user by email, username, title, or email prefix among shared friends."""
        clean_email = normalize_str(email)
        if not clean_email:
            return None
        email_prefix = clean_email.split("@")[0] if "@" in clean_email else clean_email
        account = self.get_account()

        try:
            users_list = account.users()
        except Exception:
            users_list = []

        for u in users_list:
            user_email = getattr(u, "email", None)
            user_username = getattr(u, "username", None)
            user_title = getattr(u, "title", None)

            if user_email and normalize_str(user_email) == clean_email:
                return u
            if user_username and normalize_str(user_username) == clean_email:
                return u
            if user_title and normalize_str(user_title) == clean_email:
                return u
            if user_username and normalize_str(user_username) == email_prefix:
                return u
            if user_title and normalize_str(user_title) == email_prefix:
                return u

        return None

    def get_all_shared_users(self) -> List[Dict[str, Any]]:
        """
        Retrieves all shared users on the Plex account.
        Returns a list of dicts: [{"email": "...", "username": "...", "title": "...", "id": "..."}]
        """
        account = self.get_account()
        users = account.users()
        shared_list = []
        for u in users:
            email = getattr(u, "email", None)
            if email:
                email = email.strip().lower()
            username = getattr(u, "username", None)
            title = getattr(u, "title", None)
            user_id = getattr(u, "id", None)
            
            shared_list.append({
                "email": email,
                "username": username,
                "title": title,
                "id": user_id,
                "raw_user": u
            })
        return shared_list

    def revoke_user_access(
        self,
        email: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Revokes or limits Plex library access for a user identified by email address.
        Cancels pending invitations if unaccepted, or removes/updates shared libraries if accepted.
        If PLEX_LIBRARIES is configured in .env (e.g. Peliculas,Series):
            Removes only those libraries for the user. If no remaining libraries are left, removes user access.
        If PLEX_LIBRARIES is empty or "ALL":
            Unshares the user completely from the server/account.
        """
        clean_email = email.strip().lower()
        target_libraries = self.cfg.PLEX_LIBRARIES
        
        account = self.get_account()
        user_to_modify = self.find_user_by_email(clean_email)

        # Check for pending invitation if user not found in accepted friends
        pending_invite = None
        try:
            pending_invite = account.pendingInvite(clean_email, includeReceived=False)
        except Exception:
            pass

        if not user_to_modify and not pending_invite:
            logger.warning(f"User with email '{clean_email}' not found in Plex shared users list or pending invites.")
            return {
                "email": clean_email,
                "found": False,
                "status": "NOT_FOUND",
                "message": f"User '{clean_email}' not found on Plex server.",
                "action": "NONE"
            }

        # If user has a pending invite (not yet accepted), cancel the invite
        if pending_invite and not user_to_modify:
            if dry_run:
                logger.info(f"[DRY-RUN] Would cancel pending invitation for '{clean_email}'.")
                return {
                    "email": clean_email,
                    "found": True,
                    "status": "DRY_RUN",
                    "message": "[DRY-RUN] Would cancel pending invitation",
                    "action": "[DRY-RUN] Cancel pending invitation"
                }
            try:
                account.cancelInvite(pending_invite)
                logger.info(f"Canceled pending invitation for '{clean_email}'.")
                return {
                    "email": clean_email,
                    "found": True,
                    "status": "SUCCESS",
                    "message": "Canceled pending invitation on Plex server.",
                    "action": "Canceled pending invitation"
                }
            except Exception as e:
                logger.error(f"Failed to cancel pending invitation for '{clean_email}': {e}")
                return {
                    "email": clean_email,
                    "found": True,
                    "status": "FAILED",
                    "message": str(e),
                    "action": "ERROR"
                }

        # If user is active friend and also has a leftover pending invite, clean up pending invite
        if pending_invite and not dry_run:
            try:
                account.cancelInvite(pending_invite)
            except Exception:
                pass

        # Full revocation / empty sections via updateFriend
        # Always remove all libraries regardless of PLEX_LIBRARIES env setting
        action_desc = "Revoked library access on Plex server"
        if dry_run:
            logger.info(f"[DRY-RUN] Would update library access (empty sections) for '{clean_email}'.")
            return {
                "email": clean_email,
                "found": True,
                "status": "DRY_RUN",
                "message": "[DRY-RUN] Would update library access",
                "action": action_desc
            }

        try:
            server = self.get_server()
            logger.info(f"Revoking all library access (removeSections=True) for user '{clean_email}'.")
            update_friend_sections(
                account=account,
                user=user_to_modify,
                server=server,
                sections=[],
                remove_sections=True
            )
            logger.info(f"Successfully updated library access (empty sections) for user '{clean_email}'.")
            return {
                "email": clean_email,
                "found": True,
                "status": "SUCCESS",
                "message": "Updated library access (empty sections).",
                "action": action_desc
            }
        except Exception as e:
            logger.error(f"Failed to update library access for user '{clean_email}': {e}")
            return {
                "email": clean_email,
                "found": True,
                "status": "FAILED",
                "message": str(e),
                "action": "ERROR"
            }

    def grant_user_access(
        self,
        email: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Grants access / shares libraries to a user in Plex as a standard Shared Friend (never Plex Home).
        Used when restoring access for paid invoices, temporary passes, or permanent passes.
        """
        clean_email = email.strip().lower()
        if dry_run:
            logger.info(f"[DRY-RUN] Would grant library access on Plex for '{clean_email}'.")
            return {
                "email": clean_email,
                "status": "DRY_RUN",
                "message": "[DRY-RUN] Access granted",
                "action": "Granted library access"
            }

        try:
            server = self.get_server()
            account = self.get_account()
            
            # Fetch available library sections on server
            all_sections = server.library.sections()
            target_libraries = self.cfg.PLEX_LIBRARIES

            if target_libraries:
                sections = [
                    sec for sec in all_sections 
                    if is_section_in_targets(get_section_title(sec), target_libraries)
                ]
                logger.info(
                    f"Sharing {len(sections)} of {len(all_sections)} section(s) "
                    f"matching PLEX_LIBRARIES [{', '.join(target_libraries)}] with user '{clean_email}'..."
                )
            else:
                sections = all_sections
                logger.info(f"Sharing all {len(sections)} library section(s) with user '{clean_email}'...")
            
            existing_user = self.find_user_by_email(clean_email)
            if existing_user:
                try:
                    update_friend_sections(account=account, user=existing_user, server=server, sections=sections)
                    logger.info(f"Successfully updated library access for existing Plex user '{clean_email}'.")
                except Exception as e_up:
                    logger.warning(f"Could not update_friend_sections for '{clean_email}', retrying inviteFriend: {e_up}")
                    account.inviteFriend(user=clean_email, server=server, sections=sections)
            else:
                account.inviteFriend(user=clean_email, server=server, sections=sections)
                logger.info(f"Successfully invited user '{clean_email}' as a shared Friend.")

            return {
                "email": clean_email,
                "status": "SUCCESS",
                "message": f"Granted access to {len(sections)} library sections.",
                "action": "Granted library access"
            }
        except Exception as e:
            # If user is already a friend/shared, try updating sections
            if "already" in str(e).lower():
                logger.info(f"User '{clean_email}' is already shared on Plex. Access confirmed.")
                return {
                    "email": clean_email,
                    "status": "SUCCESS",
                    "message": "User is already shared on Plex.",
                    "action": "Confirmed existing access"
                }
            logger.error(f"Failed to grant Plex access for '{clean_email}': {e}")
            return {
                "email": clean_email,
                "status": "FAILED",
                "message": str(e),
                "action": "ERROR"
            }
