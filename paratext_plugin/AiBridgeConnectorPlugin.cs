using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.Text;
using System.Threading;
using Paratext.PluginInterfaces;

namespace TranslationCoreAiBridge.ParatextConnector
{
    /// <summary>
    /// Paratext 9.5 companion for translationCore AI Bridge.
    /// Write boundary: this plugin writes Project Notes (create a thread, add a comment,
    /// resolve) and, since 0.9.0 (#429, DECISIONS 2026-11-02), one exact verse-text replacement
    /// (`put_verse_text`) that Bridge sends only after a reviewer confirmed it and it was
    /// applied and verified on Bridge's own copy. Both go through Paratext's own write locks.
    /// It never deletes a note, never reopens one, and never restructures USFM.
    ///
    /// 0.8.0 (#358): a note is addressed by project id (`get_state` lists every project on this
    /// PC), never by whatever window happens to be active; `create_note` answers with the author
    /// and creation time Paratext recorded, the only identity a Project Note has; `list_notes`,
    /// `add_comment` and `resolve_note` find a thread again by its anchor and that first comment.
    ///
    /// 0.8.1 (#358 h): the before/after context Bridge sends with `create_note` is compared with
    /// whitespace collapsed on both sides, so a selection repeated elsewhere in the verse (a
    /// footnote) is told apart instead of refused for ever.
    /// </summary>
    public sealed class AiBridgeConnectorPlugin : IParatextStartupAutomaticPlugin, IPluginObject
    {
        private const string PluginVersion = "0.9.0";
        private IPluginHost _host;
        private NamedPipeBridgeServer _server;
        private SynchronizationContext _uiContext;
        private long _stateRevision;
        private string _lastEvent = "startup";
        private string _lastOriginId = String.Empty;
        private readonly object _stateLock = new object();

        public string Name { get { return "translationCore AI Bridge Connector"; } }
        public string Publisher { get { return "translationCore AI Bridge"; } }
        public Version Version { get { return new Version(0, 9, 0, 0); } }
        public string VersionString { get { return PluginVersion; } }

        public string GetDescription(string locale)
        {
            return "Local connector for translationCore AI Bridge: Paratext user/project state, " +
                   "two-way Scripture navigation, selected text, Project Notes (create, reply, resolve) and " +
                   "one reviewer-confirmed exact verse-text replacement under Paratext's write lock.";
        }

        public IDataFileMerger GetMerger(IPluginHost host, string dataIdentifier)
        {
            return null;
        }

        public void Run(IPluginHost host)
        {
            if (host == null) throw new ArgumentNullException("host");
            _host = host;
            _uiContext = SynchronizationContext.Current;

            _host.VerseRefChanged += OnVerseRefChanged;
            _host.ActiveWindowSelectionChanged += OnActiveWindowSelectionChanged;
            _host.ShuttingDown += OnShuttingDown;

            _server = new NamedPipeBridgeServer(HandlePipeRequest);
            _server.Start();
            TouchState("startup", String.Empty);
        }

        private void OnVerseRefChanged(IPluginHost sender, IVerseRef newReference, SyncReferenceGroup group)
        {
            TouchState("reference_changed", String.Empty);
        }

        private void OnActiveWindowSelectionChanged(IPluginHost sender, IParatextChildState activeWindowState, IReadOnlyList<ISelection> currentSelections)
        {
            TouchState("selection_changed", String.Empty);
        }

        private void OnShuttingDown(object sender, CancelEventArgs e)
        {
            try
            {
                if (_host != null)
                {
                    _host.VerseRefChanged -= OnVerseRefChanged;
                    _host.ActiveWindowSelectionChanged -= OnActiveWindowSelectionChanged;
                    _host.ShuttingDown -= OnShuttingDown;
                }
            }
            catch { }
            try { if (_server != null) _server.Dispose(); }
            catch { }
            _server = null;
        }

        private void TouchState(string eventName, string originId)
        {
            lock (_stateLock)
            {
                _stateRevision++;
                _lastEvent = eventName ?? String.Empty;
                if (!String.IsNullOrEmpty(originId)) _lastOriginId = originId;
            }
        }

        private BridgeResponse HandlePipeRequest(BridgeRequest request)
        {
            BridgeResponse response = null;
            Exception failure = null;
            Action action = delegate
            {
                try { response = HandleOnParatextThread(request); }
                catch (Exception ex) { failure = ex; }
            };

            if (_uiContext != null && SynchronizationContext.Current != _uiContext)
                _uiContext.Send(delegate(object ignored) { action(); }, null);
            else
                action();

            if (failure != null)
                return new BridgeResponse { ok = false, error = failure.Message, plugin_version = PluginVersion };
            return response ?? new BridgeResponse { ok = false, error = "Paratext connector returned no response.", plugin_version = PluginVersion };
        }

        private BridgeResponse HandleOnParatextThread(BridgeRequest request)
        {
            string action = (request.action ?? String.Empty).Trim().ToLowerInvariant();
            if (action == "get_state") return BuildStateResponse();
            if (action == "set_reference") return SetReference(request.payload);
            if (action == "create_note") return CreateNote(request.payload);
            if (action == "list_notes") return ListNotes(request.payload);
            if (action == "add_comment") return AddComment(request.payload);
            if (action == "resolve_note") return ResolveNote(request.payload);
            if (action == "put_verse_text") return PutVerseText(request.payload);
            return new BridgeResponse { ok = false, error = "Unsupported connector action: " + action, plugin_version = PluginVersion };
        }

        // ---- put_verse_text (0.9.0, #429, #438) ----------------------------------------
        //
        // The one Scripture write. Bridge sends it only after a reviewer confirmed the
        // correction and it was applied and verified on Bridge's own copy of the verse
        // (DECISIONS 2026-11-02, Benz). It uses the token API the installed 9.5.110.1
        // interfaces (2.0.100.0) actually expose and that selvabenz/Paratext-sug-in-context-menu
        // exercised on this host (#438: `PutUSFM` takes (lock, usfm, bookNum), not a chapter):
        // `CanEdit`, a chapter-scoped `RequestWriteLock`, `GetUSFMTokens(book, chapter)`, one
        // Scripture text token of the verse replaced, `PutUSFMTokens(lock, tokens, book)`,
        // `SendNotifications`, then `GetUSFMTokens` again: `verified` is true only when the
        // chapter's USFM reads exactly as expected. The exact `original` must occur once in the
        // verse's Scripture text tokens (never in a footnote or cross-reference token, never
        // across two tokens, on text-element boundaries), repeats told apart by the note's own
        // before/after context (whitespace-collapsed). Anything else is refused with nothing
        // changed. Paratext records its own logged-in user as the editor; the Bridge user who
        // confirmed it is `bridge_user`, echoed in the answer for Bridge's evidence, never
        // impersonated. A history point is taken before and after, as the reference plugin does.

        private BridgeResponse PutVerseText(IDictionary<string, object> payload)
        {
            IProject project;
            string projectError;
            if (!TryResolveProject(payload, out project, out projectError))
                return Fail(projectError);
            int bookNum, chapterNum;
            string whereError;
            if (!TryResolveChapter(project, payload, out bookNum, out chapterNum, out whereError))
                return Fail(whereError);
            string verse = BridgeJson.GetString(payload, "verse").Trim();
            string original = BridgeJson.GetString(payload, "original");
            string replacement = BridgeJson.GetString(payload, "replacement");
            string beforeContext = BridgeJson.GetString(payload, "before_context");
            string afterContext = BridgeJson.GetString(payload, "after_context");
            string bridgeUser = BridgeJson.GetString(payload, "bridge_user").Trim();
            bool allowDelete = BridgeJson.GetBool(payload, "allow_delete");
            int firstVerse, lastVerse;
            if (!ParseVerseRange(verse, out firstVerse, out lastVerse)) return Fail("verse is required (a number, or a bridge like 3-4).");
            if (String.IsNullOrEmpty(original)) return Fail("original is required: the exact text to replace.");
            if (replacement == null) replacement = String.Empty;
            if (replacement.Length == 0 && !allowDelete) return Fail("An empty replacement deletes text; Bridge did not confirm a deletion.");
            if (replacement.IndexOf('\\') >= 0 || replacement.IndexOf('\n') >= 0 || replacement.IndexOf('\r') >= 0)
                return Fail("The replacement carries a USFM marker or a line break; that is a structural change the connector does not make.");
            if (String.Equals(original, replacement, StringComparison.Ordinal)) return Fail("The original and the replacement are identical; nothing to change.");
            if (project.IsResource) return Fail("Paratext project " + (project.ShortName ?? String.Empty) + " is a resource and cannot be edited.");
            bool canEdit;
            try { canEdit = project.CanEdit(this, bookNum, chapterNum); }
            catch (Exception ex)
            {
                return Fail("Paratext could not say whether this chapter may be edited: " + ex.Message);
            }
            if (!canEdit)
                return Fail("You do not have editing permission for " + BridgeJson.GetString(payload, "book") + " " +
                            chapterNum.ToString(CultureInfo.InvariantCulture) + " in " + (project.ShortName ?? String.Empty) + "; nothing was changed.");

            try { project.MakeHistoryPoint("Before Bridge correction at " + BridgeJson.GetString(payload, "book") + " " + chapterNum.ToString(CultureInfo.InvariantCulture) + ":" + verse, true); }
            catch { /* a history point that cannot be taken does not block the edit; Paratext still records it */ }

            bool revoked = false;
            IWriteLock writeLock = null;
            try
            {
                try
                {
                    writeLock = project.RequestWriteLock(this, delegate(IWriteLock requested) { revoked = true; }, bookNum, chapterNum);
                }
                catch (Exception ex)
                {
                    return Fail("Scripture WRITE_LOCK failed: " + ex.Message);
                }
                if (writeLock == null)
                    return Fail("Scripture WRITE_LOCK failed: Paratext could not grant a write lock on " +
                                (project.ShortName ?? String.Empty) + " " + BridgeJson.GetString(payload, "book") + " " +
                                chapterNum.ToString(CultureInfo.InvariantCulture) + ". Check that nothing else holds it and try again.");

                List<IUSFMToken> tokens = new List<IUSFMToken>();
                try
                {
                    IReadOnlyList<IUSFMToken> read = project.GetUSFMTokens(bookNum, chapterNum);
                    if (read != null) for (int i = 0; i < read.Count; i++) tokens.Add(read[i]);
                }
                catch (Exception ex)
                {
                    return Fail("Paratext could not read the chapter's USFM tokens: " + ex.Message);
                }
                if (tokens.Count == 0) return Fail("The chapter has no USFM tokens; nothing was changed.");

                // The verse's Scripture text, token by token, with a map back to each token.
                List<int> candidateIndexes = new List<int>();
                StringBuilder plainBuilder = new StringBuilder();
                List<int> tokenOfChar = new List<int>();     // plain index -> candidate index
                List<int> offsetOfChar = new List<int>();    // plain index -> offset in that token
                for (int i = 0; i < tokens.Count; i++)
                {
                    IUSFMTextToken text = tokens[i] as IUSFMTextToken;
                    if (text == null || text.VerseRef == null) continue;
                    if (text.IsMetadata || text.IsFigure || text.IsSpecial || text.IsFootnoteOrCrossReference || !text.IsScripture) continue;
                    if (text.VerseRef.ChapterNum != chapterNum) continue;
                    if (text.VerseRef.VerseNum < firstVerse || text.VerseRef.VerseNum > lastVerse) continue;
                    string t = text.Text ?? String.Empty;
                    int candidate = candidateIndexes.Count;
                    candidateIndexes.Add(i);
                    for (int k = 0; k < t.Length; k++)
                    {
                        plainBuilder.Append(t[k]);
                        tokenOfChar.Add(candidate);
                        offsetOfChar.Add(k);
                    }
                }
                string plain = plainBuilder.ToString();
                if (candidateIndexes.Count == 0)
                    return Fail("Verse " + verse + " has no Scripture text in the chapter's tokens; nothing was changed.");

                List<int> found = new List<int>();
                int[] elements = StringInfo.ParseCombiningCharacters(plain);
                int from = 0;
                while (from <= plain.Length - original.Length)
                {
                    int at = plain.IndexOf(original, from, StringComparison.Ordinal);
                    if (at < 0) break;
                    from = at + 1;
                    int end = at + original.Length;
                    if (Array.BinarySearch(elements, at) < 0 || (end < plain.Length && Array.BinarySearch(elements, end) < 0)) continue;
                    if (tokenOfChar[at] != tokenOfChar[end - 1]) continue;       // runs across two tokens (markup between)
                    found.Add(at);
                }
                int chosen = -1;
                if (found.Count == 1) chosen = found[0];
                else if (found.Count > 1)
                {
                    string before = Collapse(beforeContext), after = Collapse(afterContext);
                    List<int> anchored = new List<int>();
                    for (int i = 0; i < found.Count; i++)
                    {
                        string left = Collapse(plain.Substring(0, found[i]));
                        string right = Collapse(plain.Substring(found[i] + original.Length));
                        bool okBefore = before.Length == 0 || left.EndsWith(before, StringComparison.Ordinal);
                        bool okAfter = after.Length == 0 || right.StartsWith(after, StringComparison.Ordinal);
                        if ((before.Length > 0 || after.Length > 0) && okBefore && okAfter) anchored.Add(found[i]);
                    }
                    if (anchored.Count == 1) chosen = anchored[0];
                }
                if (found.Count == 0)
                    return Fail("The original text was not found in verse " + verse + " (outside its notes). It may already be corrected or changed since review; nothing was changed.");
                if (chosen < 0)
                    return Fail("The original text occurs " + found.Count.ToString(CultureInfo.InvariantCulture) +
                                " times in verse " + verse + " and the context does not identify one; nothing was changed.");

                int tokenIndex = candidateIndexes[tokenOfChar[chosen]];
                int offset = offsetOfChar[chosen];
                IUSFMTextToken old = tokens[tokenIndex] as IUSFMTextToken;
                if (old == null) return Fail("The selected target is not a Scripture text token; nothing was changed.");
                string oldText = old.Text ?? String.Empty;
                if (offset + original.Length > oldText.Length || String.CompareOrdinal(oldText, offset, original, 0, original.Length) != 0)
                    return Fail("The matched text changed before replacement; nothing was changed.");
                string newText = oldText.Substring(0, offset) + replacement + oldText.Substring(offset + original.Length);
                tokens[tokenIndex] = new ChangedTextToken(old, newText);

                string expected;
                try { expected = project.ConvertToUSFMString(tokens); }
                catch (Exception ex)
                {
                    return Fail("Paratext could not render the edited chapter as USFM: " + ex.Message);
                }
                if (revoked) return Fail("The Scripture write lock was withdrawn before the write; nothing was changed.");
                try
                {
                    project.PutUSFMTokens(writeLock, tokens, bookNum);
                    writeLock.SendNotifications();
                }
                catch (Exception ex)
                {
                    return Fail("Scripture PUT_USFM_TOKENS failed for verse " + verse + ": " + ex.Message);
                }
                string saved;
                try
                {
                    List<IUSFMToken> again = new List<IUSFMToken>();
                    IReadOnlyList<IUSFMToken> reread = project.GetUSFMTokens(bookNum, chapterNum);
                    if (reread != null) for (int i = 0; i < reread.Count; i++) again.Add(reread[i]);
                    saved = project.ConvertToUSFMString(again);
                }
                catch (Exception ex)
                {
                    BridgeResponse partial = BuildScriptureResponse(project, oldText, newText, false, bridgeUser);
                    partial.message = "The verse was written but could not be read back: " + ex.Message + ". Treat the edit as unverified.";
                    return partial;
                }
                bool verified = String.Equals(saved, expected, StringComparison.Ordinal);
                TouchState("scripture_verse_written", String.Empty);
                try { project.MakeHistoryPoint("Bridge correction at " + BridgeJson.GetString(payload, "book") + " " + chapterNum.ToString(CultureInfo.InvariantCulture) + ":" + verse, true); }
                catch { }
                BridgeResponse r = BuildScriptureResponse(project, oldText, newText, verified, bridgeUser);
                r.message = verified
                    ? "Verse " + verse + " written in " + (project.ShortName ?? String.Empty) + " and read back."
                    : "Verse " + verse + " was written but the chapter does not read back as expected; treat the edit as unverified.";
                return r;
            }
            finally
            {
                try { if (writeLock != null) writeLock.Dispose(); }
                catch { }
            }
        }

        private BridgeResponse BuildScriptureResponse(IProject project, string before, string after, bool verified, string bridgeUser)
        {
            BridgeResponse r = new BridgeResponse();
            r.ok = true;
            r.plugin_version = PluginVersion;
            r.project_id = project.ID ?? String.Empty;
            r.project_name = project.ShortName ?? String.Empty;
            r.scripture_written = true;
            r.verified = verified;
            r.usfm_before = before;
            r.usfm_after = after;
            r.author = _host.UserInfo == null ? String.Empty : (_host.UserInfo.Name ?? String.Empty);
            r.bridge_user = bridgeUser;
            r.created = FormatCreated(DateTime.Now);
            return r;
        }

        /// <summary>"3" -> (3, 3); a bridge "3-4" -> (3, 4); "4a" -> (4, 4).</summary>
        private static bool ParseVerseRange(string verse, out int first, out int last)
        {
            first = 0;
            last = 0;
            if (String.IsNullOrEmpty(verse)) return false;
            string[] parts = verse.Split('-');
            if (!TryLeadingNumber(parts[0], out first)) return false;
            last = first;
            if (parts.Length > 1 && TryLeadingNumber(parts[1], out last) && last < first) last = first;
            return true;
        }

        private static bool TryLeadingNumber(string text, out int value)
        {
            value = 0;
            int end = 0;
            while (end < text.Length && Char.IsDigit(text[end])) end++;
            return end > 0 && Int32.TryParse(text.Substring(0, end), NumberStyles.None, CultureInfo.InvariantCulture, out value);
        }

        private static string Collapse(string text)
        {
            if (String.IsNullOrEmpty(text)) return String.Empty;
            StringBuilder sb = new StringBuilder(text.Length);
            bool space = false;
            for (int i = 0; i < text.Length; i++)
            {
                if (Char.IsWhiteSpace(text[i])) { space = true; continue; }
                if (space && sb.Length > 0) sb.Append(' ');
                space = false;
                sb.Append(text[i]);
            }
            return sb.ToString();
        }

        /// <summary>A text token with its text replaced and everything else as the host gave it
        /// (the shape selvabenz/Paratext-sug-in-context-menu compiled and ran against 2.0.100.0).</summary>
        private sealed class ChangedTextToken : IUSFMTextToken
        {
            private readonly IUSFMTextToken _source;
            private readonly string _text;
            public ChangedTextToken(IUSFMTextToken original, string value) { _source = original; _text = value; }
            public string Text { get { return _text; } }
            public IVerseRef VerseRef { get { return _source.VerseRef; } }
            public int VerseOffset { get { return _source.VerseOffset; } }
            public bool IsSpecial { get { return _source.IsSpecial; } }
            public bool IsFigure { get { return _source.IsFigure; } }
            public bool IsFootnoteOrCrossReference { get { return _source.IsFootnoteOrCrossReference; } }
            public bool IsScripture { get { return _source.IsScripture; } }
            public bool IsMetadata { get { return _source.IsMetadata; } }
            public bool IsPublishableVernacular { get { return _source.IsPublishableVernacular; } }
        }

        // ---- state -------------------------------------------------------------------------

        private BridgeResponse BuildStateResponse()
        {
            IParatextChildState window = _host.ActiveWindowState;
            IReadOnlyProject project = window == null ? null : window.Project;
            IScriptureTextSelection selection = FirstScriptureSelection(window == null ? null : window.Selections);

            long revision;
            string lastEvent;
            string lastOrigin;
            lock (_stateLock)
            {
                revision = _stateRevision;
                lastEvent = _lastEvent;
                lastOrigin = _lastOriginId;
            }

            BridgeResponse r = new BridgeResponse();
            r.ok = true;
            r.user = _host.UserInfo == null ? String.Empty : (_host.UserInfo.Name ?? String.Empty);
            r.project_name = project == null ? String.Empty : (project.ShortName ?? String.Empty);
            r.project_id = project == null ? String.Empty : (project.ID ?? String.Empty);
            r.project_language = project == null ? String.Empty : (project.LanguageName ?? String.Empty);
            r.reference = window == null ? String.Empty : FormatReference(window.VerseRef);
            r.selected_text = selection == null ? String.Empty : (selection.SelectedText ?? String.Empty);
            r.selection_reference = selection == null ? String.Empty : FormatReference(selection.VerseRefStart);
            r.before_context = selection == null ? String.Empty : (selection.BeforeContext ?? String.Empty);
            r.after_context = selection == null ? String.Empty : (selection.AfterContext ?? String.Empty);
            r.selection_offset = selection == null ? -1 : selection.Offset;
            r.sync_group = window == null ? String.Empty : window.SyncReferenceGroup.ToString();
            r.paratext_version = _host.ApplicationVersion == null ? String.Empty : _host.ApplicationVersion.ToString();
            r.plugin_version = PluginVersion;
            r.state_revision = revision;
            r.last_event = lastEvent;
            r.last_origin_id = lastOrigin;
            r.projects = ListProjects();
            r.capabilities = new string[] {
                "state", "navigation", "selection", "project_notes",
                "project_list", "create_note", "list_notes", "add_comment", "resolve_note",
                "put_verse_text",
            };
            return r;
        }

        /// <summary>Every project Paratext holds on this PC, resources left out: Bridge matches
        /// `id` against the Guid the book was imported from (its link), never the active window.</summary>
        private List<Dictionary<string, object>> ListProjects()
        {
            List<Dictionary<string, object>> list = new List<Dictionary<string, object>>();
            IReadOnlyList<IProject> all = null;
            try { all = _host.GetAllProjects(); }
            catch { all = null; }
            if (all == null) return list;
            for (int i = 0; i < all.Count; i++)
            {
                IProject project = all[i];
                if (project == null) continue;
                Dictionary<string, object> entry = new Dictionary<string, object>();
                entry["id"] = project.ID ?? String.Empty;
                entry["short_name"] = project.ShortName ?? String.Empty;
                entry["long_name"] = project.LongName ?? String.Empty;
                entry["language"] = project.LanguageName ?? String.Empty;
                entry["type"] = project.Type.ToString();
                // Whether a Project Note can be written to it: a resource is read-only; anything
                // else is tried through the write lock, which is the real answer.
                entry["editable"] = !project.IsResource;
                list.Add(entry);
            }
            return list;
        }

        private BridgeResponse SetReference(IDictionary<string, object> payload)
        {
            IParatextChildState window = _host.ActiveWindowState;
            if (window == null || window.Project == null)
                return Fail("Open a Paratext Scripture project window before synchronizing navigation.");

            string text = BridgeJson.GetString(payload, "reference").Trim().ToUpperInvariant();
            string originId = BridgeJson.GetString(payload, "origin_id");
            if (String.IsNullOrEmpty(text))
                return Fail("Scripture reference is empty.");

            SyncReferenceGroup group = window.SyncReferenceGroup;
            if (group == SyncReferenceGroup.None)
                return Fail("The active Paratext window is not in a scroll/sync group. Put it in group A-E, then retry.");

            IVerseRef verseRef;
            try
            {
                // Let Paratext's own versification/reference parser resolve the book. This avoids
                // hard-coding the 66-book canon and remains correct for project-specific canons.
                verseRef = window.Project.Versification.CreateReference(text);
            }
            catch (Exception ex)
            {
                return Fail("Paratext could not resolve Scripture reference " + text + ": " + ex.Message);
            }
            if (verseRef == null)
                return Fail("Paratext could not resolve Scripture reference: " + text);

            _host.SetReferenceForSyncGroup(verseRef, group);
            TouchState("reference_set_by_bridge", originId);

            BridgeResponse r = BuildStateResponse();
            r.message = "Paratext navigation updated to " + text + ".";
            return r;
        }

        // ---- the project a note belongs to ------------------------------------------------

        /// <summary>The project with `project_id` among every project on this PC. Required:
        /// 0.8.0 never writes to "whatever window is active" (#347/#358).</summary>
        private bool TryResolveProject(IDictionary<string, object> payload, out IProject project, out string error)
        {
            project = null;
            error = String.Empty;
            string wanted = BridgeJson.GetString(payload, "project_id").Trim();
            if (String.IsNullOrEmpty(wanted))
            {
                error = "project_id is required: Bridge names the Paratext project a note belongs to.";
                return false;
            }
            IReadOnlyList<IProject> all = null;
            try { all = _host.GetAllProjects(); }
            catch (Exception ex)
            {
                error = "Paratext could not list its projects: " + ex.Message;
                return false;
            }
            if (all != null)
            {
                for (int i = 0; i < all.Count; i++)
                {
                    IProject candidate = all[i];
                    if (candidate != null && String.Equals(candidate.ID, wanted, StringComparison.OrdinalIgnoreCase))
                    {
                        if (candidate.IsResource)
                        {
                            error = "Paratext project " + (candidate.ShortName ?? wanted) + " is a resource and cannot hold Project Notes.";
                            return false;
                        }
                        project = candidate;
                        return true;
                    }
                }
            }
            error = "Paratext has no project with id " + wanted + " on this computer.";
            return false;
        }

        /// <summary>The active window when it shows `project`, else null: only then is a live
        /// selection a valid anchor.</summary>
        private IParatextChildState WindowFor(IProject project)
        {
            IParatextChildState window = _host.ActiveWindowState;
            if (window == null || window.Project == null) return null;
            return String.Equals(window.Project.ID, project.ID, StringComparison.OrdinalIgnoreCase) ? window : null;
        }

        // ---- create_note ------------------------------------------------------------------

        private BridgeResponse CreateNote(IDictionary<string, object> payload)
        {
            IProject project;
            string projectError;
            if (!TryResolveProject(payload, out project, out projectError))
                return Fail(projectError);

            string referenceText = BridgeJson.GetString(payload, "reference").Trim().ToUpperInvariant();
            string selectedText = BridgeJson.GetString(payload, "selected_text");
            string beforeContext = BridgeJson.GetString(payload, "before_context");
            string afterContext = BridgeJson.GetString(payload, "after_context");
            string comment = BridgeJson.GetString(payload, "comment").Trim();
            string assigneeName = BridgeJson.GetString(payload, "assignee").Trim();
            string externalAuthor = BridgeJson.GetString(payload, "external_author").Trim();
            string noteAuthor = _host.UserInfo == null ? String.Empty : (_host.UserInfo.Name ?? String.Empty).Trim();

            if (String.IsNullOrEmpty(noteAuthor))
                return Fail("Project Note AUTHOR failed: Paratext did not expose the current logged-in user. The Bridge will not invent an AI Paratext account.");
            if (String.IsNullOrEmpty(comment)) return Fail("Reviewer note text is empty.");

            if (String.IsNullOrEmpty(referenceText))
                return Fail("Scripture reference is empty.");
            IVerseRef verseRef;
            try
            {
                verseRef = project.Versification.CreateReference(referenceText);
            }
            catch (Exception ex)
            {
                return Fail("Paratext could not resolve Scripture reference " + referenceText + ": " + ex.Message);
            }
            if (verseRef == null)
                return Fail("Paratext could not resolve Scripture reference: " + referenceText);

            IScriptureTextSelection anchor;
            string anchorError;
            if (!TryResolveAnchor(project, WindowFor(project), verseRef, selectedText, beforeContext, afterContext, out anchor, out anchorError))
                return Fail(anchorError);

            IUserInfo assignee = FindProjectUser(project, assigneeName);
            string body = comment;
            if (!String.IsNullOrEmpty(externalAuthor))
                body = "[" + externalAuthor + "]\r\n" + comment;

            IProjectNote note = null;
            BridgeResponse failure = WithNotesLock(project, delegate(IWriteLock writeLock)
            {
                try
                {
                    CommentParagraph paragraph = new CommentParagraph(new FormattedString(body));
                    note = project.AddNote(writeLock, anchor, new CommentParagraph[] { paragraph }, null, assignee);
                }
                catch (Exception ex)
                {
                    return Fail("Project Note ADD_NOTE failed for " + referenceText + " as " + noteAuthor + ": " + ex.Message);
                }
                return null;
            });
            if (failure != null) return failure;

            TouchState("project_note_created", String.Empty);
            BridgeResponse r = BuildStateResponse();
            r.note_created = true;
            IComment first = FirstComment(note);
            r.author = first == null ? noteAuthor : AuthorName(first);
            r.created = first == null ? String.Empty : FormatCreated(first.Created);
            r.anchor = AnchorDict(note == null ? anchor : (note.Anchor ?? anchor));
            r.message = "Paratext Project Note created at " + referenceText + " in " + (project.ShortName ?? String.Empty) +
                        " by " + r.author + ".";
            return r;
        }

        // ---- list_notes -------------------------------------------------------------------

        private BridgeResponse ListNotes(IDictionary<string, object> payload)
        {
            IProject project;
            string projectError;
            if (!TryResolveProject(payload, out project, out projectError))
                return Fail(projectError);
            int bookNum, chapterNum;
            string whereError;
            if (!TryResolveChapter(project, payload, out bookNum, out chapterNum, out whereError))
                return Fail(whereError);
            bool unresolvedOnly = BridgeJson.GetBool(payload, "unresolved_only");

            IReadOnlyList<IProjectNote> notes;
            try { notes = project.GetNotes(bookNum, chapterNum, unresolvedOnly); }
            catch (Exception ex)
            {
                return Fail("Paratext could not list the notes of " + BridgeJson.GetString(payload, "book") + " " +
                            BridgeJson.GetString(payload, "chapter") + ": " + ex.Message);
            }
            BridgeResponse r = new BridgeResponse();
            r.ok = true;
            r.plugin_version = PluginVersion;
            r.project_id = project.ID ?? String.Empty;
            r.project_name = project.ShortName ?? String.Empty;
            r.notes = new List<Dictionary<string, object>>();
            if (notes != null)
            {
                for (int i = 0; i < notes.Count; i++)
                {
                    if (notes[i] != null) r.notes.Add(NoteDict(notes[i]));
                }
            }
            return r;
        }

        // ---- add_comment / resolve_note ---------------------------------------------------

        private BridgeResponse AddComment(IDictionary<string, object> payload)
        {
            IProject project;
            IProjectNote note;
            BridgeResponse failure = FindNote(payload, out project, out note);
            if (failure != null) return failure;

            string text = BridgeJson.GetString(payload, "text").Trim();
            if (String.IsNullOrEmpty(text)) return Fail("Comment text is empty.");
            IUserInfo assignee = FindProjectUser(project, BridgeJson.GetString(payload, "assignee").Trim());

            IComment added = null;
            failure = WithNotesLock(project, delegate(IWriteLock writeLock)
            {
                try
                {
                    CommentParagraph paragraph = new CommentParagraph(new FormattedString(text));
                    added = note.AddNewComment(writeLock, new CommentParagraph[] { paragraph }, null, assignee);
                }
                catch (Exception ex)
                {
                    return Fail("Project Note ADD_COMMENT failed: " + ex.Message);
                }
                return null;
            });
            if (failure != null) return failure;

            TouchState("project_note_comment_added", String.Empty);
            BridgeResponse r = new BridgeResponse();
            r.ok = true;
            r.plugin_version = PluginVersion;
            r.project_id = project.ID ?? String.Empty;
            r.project_name = project.ShortName ?? String.Empty;
            r.comment_added = true;
            r.author = added == null ? (_host.UserInfo == null ? String.Empty : _host.UserInfo.Name) : AuthorName(added);
            r.created = added == null ? String.Empty : FormatCreated(added.Created);
            r.anchor = AnchorDict(note.Anchor);
            r.message = "Comment added to the Paratext note at " + FormatReference(note.Anchor == null ? null : note.Anchor.VerseRefStart) + ".";
            return r;
        }

        private BridgeResponse ResolveNote(IDictionary<string, object> payload)
        {
            IProject project;
            IProjectNote note;
            BridgeResponse failure = FindNote(payload, out project, out note);
            if (failure != null) return failure;

            bool already = note.IsResolved;
            if (!already)
            {
                failure = WithNotesLock(project, delegate(IWriteLock writeLock)
                {
                    try { note.Resolve(writeLock); }
                    catch (Exception ex)
                    {
                        return Fail("Project Note RESOLVE failed: " + ex.Message);
                    }
                    return null;
                });
                if (failure != null) return failure;
                TouchState("project_note_resolved", String.Empty);
            }

            BridgeResponse r = new BridgeResponse();
            r.ok = true;
            r.plugin_version = PluginVersion;
            r.project_id = project.ID ?? String.Empty;
            r.project_name = project.ShortName ?? String.Empty;
            r.resolved = true;
            r.anchor = AnchorDict(note.Anchor);
            r.message = already ? "The Paratext note was already resolved." : "Paratext note resolved.";
            return r;
        }

        /// <summary>The note `key` names in `project`: same verse, same anchor (offset and
        /// selected text) and, when given, the same first comment (author and created), the
        /// only identity a Paratext note carries. Exactly one must match.</summary>
        private BridgeResponse FindNote(IDictionary<string, object> payload, out IProject project, out IProjectNote note)
        {
            note = null;
            string projectError;
            if (!TryResolveProject(payload, out project, out projectError))
                return Fail(projectError);
            int bookNum, chapterNum;
            string whereError;
            if (!TryResolveChapter(project, payload, out bookNum, out chapterNum, out whereError))
                return Fail(whereError);
            IDictionary<string, object> key = BridgeJson.GetObject(payload, "key");
            if (key == null) return Fail("key is required: the note's verse_ref, offset, selected_text, first_author and first_created.");
            string verseRef = BridgeJson.GetString(key, "verse_ref").Trim().ToUpperInvariant();
            int offset = BridgeJson.GetInt(key, "offset", -1);
            string selectedText = BridgeJson.GetString(key, "selected_text");
            string firstAuthor = BridgeJson.GetString(key, "first_author").Trim();
            string firstCreated = BridgeJson.GetString(key, "first_created").Trim();
            if (String.IsNullOrEmpty(verseRef)) return Fail("key.verse_ref is required.");

            IReadOnlyList<IProjectNote> notes;
            try { notes = project.GetNotes(bookNum, chapterNum, false); }
            catch (Exception ex)
            {
                return Fail("Paratext could not list the notes of the chapter: " + ex.Message);
            }
            List<IProjectNote> matches = new List<IProjectNote>();
            if (notes != null)
            {
                for (int i = 0; i < notes.Count; i++)
                {
                    IProjectNote candidate = notes[i];
                    if (candidate == null || candidate.Anchor == null) continue;
                    if (!String.Equals(FormatReference(candidate.Anchor.VerseRefStart), verseRef, StringComparison.OrdinalIgnoreCase)) continue;
                    if (offset >= 0 && candidate.Anchor.Offset != offset) continue;
                    if (!String.Equals(candidate.Anchor.SelectedText ?? String.Empty, selectedText ?? String.Empty, StringComparison.Ordinal)) continue;
                    IComment first = FirstComment(candidate);
                    if (!String.IsNullOrEmpty(firstAuthor) && (first == null || !String.Equals(AuthorName(first), firstAuthor, StringComparison.OrdinalIgnoreCase))) continue;
                    if (!String.IsNullOrEmpty(firstCreated) && (first == null || !SameInstant(first.Created, firstCreated))) continue;
                    matches.Add(candidate);
                }
            }
            if (matches.Count == 1)
            {
                note = matches[0];
                return null;
            }
            if (matches.Count == 0)
                return Fail("No Paratext note at " + verseRef + " matches the key (anchor and first comment).");
            return Fail(matches.Count.ToString(CultureInfo.InvariantCulture) + " Paratext notes at " + verseRef +
                        " match the key; give first_author and first_created to name one.");
        }

        private static bool TryResolveChapter(IProject project, IDictionary<string, object> payload,
            out int bookNum, out int chapterNum, out string error)
        {
            bookNum = 0;
            chapterNum = 0;
            error = String.Empty;
            string book = BridgeJson.GetString(payload, "book").Trim().ToUpperInvariant();
            string chapter = BridgeJson.GetString(payload, "chapter").Trim();
            if (String.IsNullOrEmpty(book) || String.IsNullOrEmpty(chapter))
            {
                error = "book and chapter are required.";
                return false;
            }
            IVerseRef reference;
            try { reference = project.Versification.CreateReference(book + " " + chapter + ":1"); }
            catch (Exception ex)
            {
                error = "Paratext could not resolve " + book + " " + chapter + ": " + ex.Message;
                return false;
            }
            if (reference == null)
            {
                error = "Paratext could not resolve " + book + " " + chapter + ".";
                return false;
            }
            bookNum = reference.BookNum;
            chapterNum = reference.ChapterNum;
            return true;
        }

        // ---- helpers ----------------------------------------------------------------------

        /// <summary>Runs `body` under a Project Notes write lock on `project`; the lock is
        /// released whatever happens. Returns the failure response, or null on success.</summary>
        private BridgeResponse WithNotesLock(IProject project, Func<IWriteLock, BridgeResponse> body)
        {
            IWriteLock writeLock = null;
            try
            {
                try
                {
                    writeLock = project.RequestWriteLock(this, delegate(IWriteLock requested)
                    {
                        try { if (requested != null) requested.Dispose(); }
                        catch { }
                    }, WriteLockScope.ProjectNotes);
                }
                catch (Exception ex)
                {
                    return Fail("Project Note WRITE_LOCK failed: " + ex.Message);
                }
                if (writeLock == null)
                    return Fail("Project Note WRITE_LOCK failed: Paratext could not grant a Project Notes write lock on " +
                                (project.ShortName ?? String.Empty) + ". Check project permissions and try again.");
                return body(writeLock);
            }
            finally
            {
                try { if (writeLock != null) writeLock.Dispose(); }
                catch { }
            }
        }

        private static bool TryResolveAnchor(IProject project, IParatextChildState window, IVerseRef reference,
            string selectedText, string beforeContext, string afterContext,
            out IScriptureTextSelection anchor, out string error)
        {
            anchor = null;
            error = String.Empty;

            if (String.IsNullOrEmpty(selectedText))
            {
                anchor = project.GetScriptureSelectionForVerse(reference);
                if (anchor == null)
                {
                    error = "Paratext could not create a verse-level note anchor.";
                    return false;
                }
                return true;
            }

            // The live selection is an anchor only when the active window shows this project.
            IScriptureTextSelection active = window == null ? null : FirstScriptureSelection(window.Selections);
            if (active != null && String.Equals(active.SelectedText, selectedText, StringComparison.Ordinal) &&
                String.Equals(FormatReference(active.VerseRefStart), FormatReference(reference), StringComparison.OrdinalIgnoreCase))
            {
                anchor = active;
                return true;
            }

            IReadOnlyList<IScriptureTextSelection> matches = project.FindMatchingScriptureSelections(reference, selectedText, null, false, false);
            if (matches == null || matches.Count == 0)
            {
                error = "The selected text was not found in the Paratext verse. Select the exact text in Paratext and retry.";
                return false;
            }
            if (matches.Count == 1)
            {
                anchor = matches[0];
                return true;
            }

            IScriptureTextSelection contextMatch = null;
            int contextMatches = 0;
            for (int i = 0; i < matches.Count; i++)
            {
                IScriptureTextSelection candidate = matches[i];
                if (ContextCompatible(candidate.BeforeContext, beforeContext, true) &&
                    ContextCompatible(candidate.AfterContext, afterContext, false))
                {
                    contextMatch = candidate;
                    contextMatches++;
                }
            }
            if (contextMatches == 1)
            {
                anchor = contextMatch;
                return true;
            }

            error = "The selected text occurs more than once in this verse. Select the exact occurrence inside Paratext, then retry so the note cannot attach to the wrong word.";
            return false;
        }

        private static bool ContextCompatible(string actual, string supplied, bool compareSuffix)
        {
            supplied = CollapseWhitespace(supplied);
            if (supplied.Length == 0) return true;
            // Paratext's context keeps the space next to the selection; Bridge sends
            // the neighbouring word without it. Compare both with whitespace collapsed.
            actual = CollapseWhitespace(actual);
            if (supplied.Length > 80)
                supplied = compareSuffix ? supplied.Substring(supplied.Length - 80) : supplied.Substring(0, 80);
            return compareSuffix
                ? actual.EndsWith(supplied, StringComparison.Ordinal)
                : actual.StartsWith(supplied, StringComparison.Ordinal);
        }

        private static string CollapseWhitespace(string text)
        {
            if (String.IsNullOrEmpty(text)) return String.Empty;
            StringBuilder collapsed = new StringBuilder(text.Length);
            bool pendingSpace = false;
            foreach (char ch in text)
            {
                if (Char.IsWhiteSpace(ch))
                {
                    pendingSpace = collapsed.Length > 0;
                    continue;
                }
                if (pendingSpace) collapsed.Append(' ');
                pendingSpace = false;
                collapsed.Append(ch);
            }
            return collapsed.ToString();
        }

        private static IScriptureTextSelection FirstScriptureSelection(IReadOnlyList<ISelection> selections)
        {
            if (selections == null) return null;
            for (int i = 0; i < selections.Count; i++)
            {
                IScriptureTextSelection text = selections[i] as IScriptureTextSelection;
                if (text != null) return text;
            }
            return null;
        }

        private static IUserInfo FindProjectUser(IProject project, string name)
        {
            if (String.IsNullOrEmpty(name) || project.NonObserverUsers == null) return null;
            for (int i = 0; i < project.NonObserverUsers.Count; i++)
            {
                IUserInfo user = project.NonObserverUsers[i];
                if (user != null && String.Equals(user.Name, name, StringComparison.OrdinalIgnoreCase))
                    return user;
            }
            return null;
        }

        private static IComment FirstComment(IProjectNote note)
        {
            if (note == null || note.Comments == null || note.Comments.Count == 0) return null;
            return note.Comments[0];
        }

        private static string AuthorName(IComment comment)
        {
            if (comment == null || comment.Author == null) return String.Empty;
            return comment.Author.Name ?? String.Empty;
        }

        /// <summary>ISO 8601 with seven fractional digits ("o"), the precision Paratext keeps in
        /// its notes files, so Bridge can match the file's Date exactly.</summary>
        private static string FormatCreated(DateTimeOffset created)
        {
            return created.ToString("o", CultureInfo.InvariantCulture);
        }

        private static bool SameInstant(DateTimeOffset actual, string supplied)
        {
            DateTimeOffset parsed;
            if (DateTimeOffset.TryParse(supplied, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out parsed))
                return actual.UtcDateTime == parsed.UtcDateTime;
            return String.Equals(FormatCreated(actual), supplied, StringComparison.Ordinal);
        }

        private static string CommentText(IComment comment)
        {
            if (comment == null || comment.Contents == null) return String.Empty;
            StringBuilder text = new StringBuilder();
            for (int i = 0; i < comment.Contents.Count; i++)
            {
                CommentParagraph paragraph = comment.Contents[i];
                if (paragraph == null) continue;
                if (text.Length > 0) text.Append('\n');
                if (paragraph.Spans == null) continue;
                for (int j = 0; j < paragraph.Spans.Count; j++)
                {
                    FormattedString span = paragraph.Spans[j];
                    if (span != null) text.Append(span.Text ?? String.Empty);
                }
            }
            return text.ToString();
        }

        private static Dictionary<string, object> AnchorDict(IScriptureTextSelection anchor)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["verse_ref"] = anchor == null ? String.Empty : FormatReference(anchor.VerseRefStart);
            d["verse_ref_end"] = anchor == null ? String.Empty : FormatReference(anchor.VerseRefEnd);
            d["offset"] = anchor == null ? -1 : anchor.Offset;
            d["selected_text"] = anchor == null ? String.Empty : (anchor.SelectedText ?? String.Empty);
            d["before_context"] = anchor == null ? String.Empty : (anchor.BeforeContext ?? String.Empty);
            d["after_context"] = anchor == null ? String.Empty : (anchor.AfterContext ?? String.Empty);
            return d;
        }

        private static Dictionary<string, object> NoteDict(IProjectNote note)
        {
            Dictionary<string, object> d = AnchorDict(note.Anchor);
            d["is_resolved"] = note.IsResolved;
            d["assigned_user"] = note.AssignedUser == null ? String.Empty : (note.AssignedUser.Name ?? String.Empty);
            IComment first = FirstComment(note);
            d["first_author"] = AuthorName(first);
            d["first_created"] = first == null ? String.Empty : FormatCreated(first.Created);
            List<Dictionary<string, object>> comments = new List<Dictionary<string, object>>();
            if (note.Comments != null)
            {
                for (int i = 0; i < note.Comments.Count; i++)
                {
                    IComment comment = note.Comments[i];
                    if (comment == null) continue;
                    Dictionary<string, object> c = new Dictionary<string, object>();
                    c["author"] = AuthorName(comment);
                    c["created"] = FormatCreated(comment.Created);
                    c["text"] = CommentText(comment);
                    c["assigned_user"] = comment.AssignedUser == null ? String.Empty : (comment.AssignedUser.Name ?? String.Empty);
                    comments.Add(c);
                }
            }
            d["comments"] = comments;
            return d;
        }

        private static BridgeResponse Fail(string message)
        {
            return new BridgeResponse { ok = false, error = message, plugin_version = PluginVersion };
        }

        private static string FormatReference(IVerseRef reference)
        {
            if (reference == null) return String.Empty;
            return String.Format(CultureInfo.InvariantCulture, "{0} {1}:{2}", reference.BookCode, reference.ChapterNum, reference.VerseNum);
        }

    }
}
