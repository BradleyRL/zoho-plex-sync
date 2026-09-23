from typing import Optional, List, Dict, Any
from plexapi.myplex import MyPlexAccount
from config import config
from logger_service import logger

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

    def find_user_by_email(self, email: str) -> Optional[Any]:
        """Finds a shared friend/user in Plex Account matching the given email."""
        account = self.get_account()
        users = account.users()
        email_clean = email.strip().lower()

        for u in users:
            u_email = (getattr(u, "email", "") or "").strip().lower()
            u_username = (getattr(u, "username", "") or "").strip().lower()
            u_title = (getattr(u, "title", "") or "").strip().lower()

            if email_clean in (u_email, u_username, u_title):
                return u
        return None

    def revoke_user_access(
        self,
        email: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Revokes or modifies library access for a user identified by email.
        
        Behavior based on config.PLEX_LIBRARIES:
        - If config.PLEX_LIBRARIES is specified (e.g. ["Movies", "TV Shows"]):
          Removes access to those specific libraries for the target user.
        - If config.PLEX_LIBRARIES is empty / ALL:
          Removes the user friend/share connection completely.

        Returns a dictionary with result info:
        {
            "found": True/False,
            "action": "...",
            "status": "SUCCESS" / "NOT_FOUND" / "DRY_RUN" / "FAILED"
        }
        """
        try:
            account = self.get_account()
            user = self.find_user_by_email(email)

            if not user:
                logger.warning(f"User email '{email}' was NOT found in Plex shared friends.")
                return {
                    "found": False,
                    "action": "No action taken (user not found in Plex)",
                    "status": "NOT_FOUND"
                }

            restricted_libraries = self.cfg.PLEX_LIBRARIES

            if restricted_libraries:
                action_desc = f"Removed library access for: [{', '.join(restricted_libraries)}]"
                
                # Check if user already has restricted libraries removed (Idempotency check)
                user_current_sections = []
                for s in getattr(user, "servers", []):
                    try:
                        user_current_sections.extend([sec.title.lower() for sec in s.sections()])
                    except Exception:
                        pass

                restricted_lower = [lib.lower() for lib in restricted_libraries]
                # If none of the restricted libraries are currently shared with the user
                already_restricted = not any(lib in user_current_sections for lib in restricted_lower) if user_current_sections else False

                if already_restricted:
                    logger.info(f"User '{email}' already has libraries [{', '.join(restricted_libraries)}] revoked.")
                    return {
                        "found": True,
                        "action": f"Libraries already revoked previously: [{', '.join(restricted_libraries)}]",
                        "status": "ALREADY_DISABLED"
                    }

                if dry_run:
                    return {
                        "found": True,
                        "action": f"[DRY-RUN] Would execute: {action_desc}",
                        "status": "DRY_RUN"
                    }

                # Get the server instance
                server_name = self.cfg.PLEX_SERVER_NAME
                if server_name:
                    server = account.server(server_name)
                else:
                    # Default to the first available server owned by account
                    resources = account.resources()
                    owned_servers = [s for s in resources if getattr(s, "owned", False)]
                    if not owned_servers:
                        raise RuntimeError("No owned Plex servers found in this Plex account.")
                    server = owned_servers[0].connect()

                # Get all available library sections
                all_sections = server.library.sections()
                
                # Filter out the restricted libraries
                remaining_sections = [
                    sec for sec in all_sections if sec.title.lower() not in restricted_lower
                ]

                # Update user shared sections
                account.updateFriend(user=user, server=server, sections=remaining_sections)
                return {
                    "found": True,
                    "action": action_desc,
                    "status": "SUCCESS"
                }

            else:
                # Remove friend / share access completely
                action_desc = "Removed server sharing & friend access completely"
                
                if dry_run:
                    return {
                        "found": True,
                        "action": f"[DRY-RUN] Would execute: {action_desc}",
                        "status": "DRY_RUN"
                    }

                account.removeFriend(user)
                return {
                    "found": True,
                    "action": action_desc,
                    "status": "SUCCESS"
                }

        except Exception as e:
            logger.error(f"Error revoking Plex access for '{email}': {e}")
            return {
                "found": True,
                "action": f"Failed: {str(e)}",
                "status": "FAILED"
            }

    def grant_user_access(
        self,
        email: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Grants or restores library access to a user on Plex.
        If user is not yet a friend, sends an invite.
        If user is already a friend, updates their library sections.
        """
        email_clean = email.strip().lower()
        try:
            account = self.get_account()
            user = self.find_user_by_email(email_clean)

            # Get the server instance
            server_name = self.cfg.PLEX_SERVER_NAME
            if server_name:
                server = account.server(server_name)
            else:
                resources = account.resources()
                owned_servers = [s for s in resources if getattr(s, "owned", False)]
                if not owned_servers:
                    raise RuntimeError("No owned Plex servers found in this Plex account.")
                server = owned_servers[0].connect()

            all_sections = server.library.sections()

            # Determine target sections to grant
            restricted_libraries = self.cfg.PLEX_LIBRARIES
            if restricted_libraries:
                target_libraries = [lib.lower() for lib in restricted_libraries]
                # If restricted_libraries was specified, grant access to those configured libraries
                target_sections = [
                    sec for sec in all_sections if sec.title.lower() in target_libraries
                ]
                if not target_sections:
                    # Fallback to all sections if none matched by name
                    target_sections = all_sections
            else:
                # Grant access to all sections
                target_sections = all_sections

            section_names = [sec.title for sec in target_sections]
            action_desc = f"Granted library access for: [{', '.join(section_names)}]"

            if dry_run:
                return {
                    "found": user is not None,
                    "action": f"[DRY-RUN] Would execute: {action_desc}",
                    "status": "DRY_RUN"
                }

            if user:
                # User exists in Plex friends -> Update shared sections
                account.updateFriend(user=user, server=server, sections=target_sections)
                logger.info(f"Updated access for Plex user '{email_clean}': [{', '.join(section_names)}]")
            else:
                # User does not exist in Plex friends -> Invite user
                account.inviteFriend(user=email_clean, server=server, sections=target_sections)
                logger.info(f"Invited new user '{email_clean}' to Plex server with libraries: [{', '.join(section_names)}]")

            return {
                "found": True,
                "action": action_desc,
                "status": "SUCCESS"
            }

        except Exception as e:
            logger.error(f"Error granting Plex access for '{email_clean}': {e}")
            return {
                "found": False,
                "action": f"Failed: {str(e)}",
                "status": "FAILED"
            }

    def get_all_shared_users(self) -> List[Dict[str, str]]:
        """Returns a list of dicts for all users currently shared on Plex."""
        account = self.get_account()
        users = account.users()
        result = []
        for u in users:
            result.append({
                "email": (getattr(u, "email", "") or "").strip().lower(),
                "username": (getattr(u, "username", "") or "").strip(),
                "title": (getattr(u, "title", "") or "").strip()
            })
        return result
