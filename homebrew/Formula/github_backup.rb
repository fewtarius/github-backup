# typed: false
# frozen_string_literal: true

class GithubBackup < Formula
  desc "Comprehensive GitHub backup tool - mirrors repos, gists, wikis, and metadata"
  homepage "https://github.com/fewtarius/github-backup"
  url "https://github.com/fewtarius/github-backup/archive/refs/tags/vTAG_VERSION.tar.gz"
  sha256 "sha256SHA256_PLACEHOLDER"
  license "MIT"
  head "https://github.com/fewtarius/github-backup.git", branch: "main"

  depends_on "python@3.12"
  depends_on "git"

  def install
    # Install Python package
    system "python3.12", "-m", "pip", "install", ".", "--prefix=#{prefix}", "--no-deps"

    # Install wrapper script
    bin.install_symlink prefix/"bin/github-backup" => "github-backup"
  end

  test do
    # Verify the entry point is executable
    assert_match "GitHub backup", shell_output("#{bin}/github-backup --help 2>&1")
  end
end