from __future__ import annotations
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

    def get_server(self):
        account = self.get_account()
        server_name = self.cfg.PLEX_SERVER_NAME
        
        if server_name:
            logger.info(f"Finding specified Plex server: '{server_name}'...")
            return account.resource(server_name).connect()
        else:
            # If server name is not explicitly set, use the first owned server resource
            resources = [r for r in account.resources() if r.provides == "server" and r.owned]
            if not resources:
                raise RuntimeError("No owned Plex server resource found on account.")
            target_resource = resources[0]
            logger.info(f"Using default owned Plex server: '{target_resource.name}'...")
            return target_resource.connect()

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
        If PLEX_LIBRARIES is configured in .env (e.g. Peliculas,Series):
            Removes only those libraries for the user.
        If PLEX_LIBRARIES is empty or "ALL":
            Unshares the user completely from the server/account.
        """
        clean_email = email.strip().lower()
        target_libraries = self.cfg.PLEX_LIBRARIES
        
        account = self.get_account()
        user_to_modify = None
        
        logger.info(f"Searching Plex account for user with email '{clean_email}'...")
        for u in account.users():
            user_email = getattr(u, "email", None)
            user_username = getattr(u, "username", None)
            user_title = getattr(u, "title", None)

            if user_email and user_email.strip().lower() == clean_email:
                user_to_modify = u
                break
            # Fallback match by username or title if email match fails
            if user_username and user_username.strip().lower() == clean_email:
                user_to_modify = u
                break
            if user_title and user_title.strip().lower() == clean_email:
                user_to_modify = u
                break

        if not user_to_modify:
            logger.warning(f"User with email '{clean_email}' not found in Plex shared users list.")
            return {
                "email": clean_email,
                "status": "NOT_FOUND",
                "message": f"User '{clean_email}' not found on Plex server.",
                "action": "NONE"
            }

        # Check if libraries to remove are specified, or if we unshare completely
        if target_libraries:
            action_desc = f"Removed libraries [{', '.join(target_libraries)}]"
            if dry_run:
                logger.info(f"[DRY-RUN] Would update library access for '{clean_email}', removing [{', '.join(target_libraries)}].")
                return {
                    "email": clean_email,
                    "status": "DRY_RUN",
                    "message": f"[DRY-RUN] Would remove libraries [{', '.join(target_libraries)}]",
                    "action": action_desc
                }
            
            try:
                # Fetch currently shared sections for this user
                shared_sections = getattr(user_to_modify, "servers", [])
                server_name = self.cfg.PLEX_SERVER_NAME
                
                # Get section titles user currently has access to
                current_sections = []
                for s in user_to_modify.servers:
                    if not server_name or s.name == server_name:
                        current_sections = getattr(s, "sections", [])
                        break

                # Filter out target libraries
                target_libs_lower = {lib.lower() for lib in target_libraries}
                remaining_sections = [
                    sec for sec in current_sections 
                    if getattr(sec, "title", "").lower() not in target_libs_lower
                ]

                # Update user access on server with remaining sections
                server = self.get_server()
                server.updateUnshare(user_to_modify, sections=remaining_sections)
                logger.info(f"Successfully updated library access for user '{clean_email}'. Remaining sections: {[getattr(s, 'title', '') for s in remaining_sections]}")
                return {
                    "email": clean_email,
                    "status": "SUCCESS",
                    "message": f"Updated library access, removed [{', '.join(target_libraries)}]",
                    "action": action_desc
                }
            except Exception as e:
                logger.error(f"Failed to update library access for user '{clean_email}': {e}")
                return {
                    "email": clean_email,
                    "status": "FAILED",
                    "message": str(e),
                    "action": "ERROR"
                }
        else:
            # Full unshare / revocation
            action_desc = "Unshared user completely from Plex server"
            if dry_run:
                logger.info(f"[DRY-RUN] Would completely unshare user '{clean_email}' from Plex.")
                return {
                    "email": clean_email,
                    "status": "DRY_RUN",
                    "message": "[DRY-RUN] Would unshare user completely",
                    "action": action_desc
                }

            try:
                server = self.get_server()
                account.removeFriend(user_to_modify)
                logger.info(f"Successfully unshared/removed user '{clean_email}' from Plex.")
                return {
                    "email": clean_email,
                    "status": "SUCCESS",
                    "message": "Unshared user completely from Plex server.",
                    "action": action_desc
                }
            except Exception as e:
                logger.error(f"Failed to unshare user '{clean_email}' from Plex: {e}")
                return {
                    "email": clean_email,
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
        Grants access / shares libraries to a user in Plex.
        Used when restoring access for paid invoices or temporary passes.
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
            sections = server.library.sections()
            logger.info(f"Sharing {len(sections)} library section(s) with user '{clean_email}'...")
            
            account.inviteFriend(user=clean_email, server=server, sections=sections)
            logger.info(f"Successfully granted library access on Plex for '{clean_email}'.")
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
